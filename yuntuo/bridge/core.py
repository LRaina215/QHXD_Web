"""FpgaBridge：独占 FPGA 导航链路的单线程循环（tick），HTTP 线程只往命令队列里放请求。"""
from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from yuntuo.bridge.config import BridgeConfig, load_routes, load_waypoints
from yuntuo.bridge.inputs import RateMeter
from yuntuo.bridge.feedback import FEEDBACK_MAX_AGE_S, StopEvidence
from yuntuo.bridge.poster import BackendPoster
from yuntuo.bridge.tasks import StatusView, TaskRunner, utc_now
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link.links import LinkError, NavLink, open_link
from yuntuo.fpga_link.nvmp import MapPackageError, PriorMap, parse_package
from yuntuo.fpga_link.telemetry import ControlFrame

log = logging.getLogger("fpga_bridge")


class MapUploadAborted(RuntimeError):
    pass


@dataclass
class PendingRequest:
    kind: str                     # mission | estop | set_pose | map
    payload: dict
    ready: threading.Event = field(default_factory=threading.Event)
    response: dict | None = None


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FpgaBridge:
    def __init__(self, cfg: BridgeConfig, *, link_factory: Callable[[], NavLink] | None = None,
                 clock: Callable[[], float] = time.monotonic, poster: Any = None,
                 perception: Any = None, telemetry: Any = None) -> None:
        self.cfg = cfg
        self.clock = clock
        self.link_factory = link_factory or (lambda: open_link(cfg.link, local_port=cfg.local_udp_port))
        self.link: NavLink | None = None
        self.link_error: str | None = None
        self.reconnect_at = 0.0
        self.outbox: deque[bytes] = deque()
        self.status: nv.NavStatus | None = None
        self.status_at = -1e9
        self.status_rate = RateMeter()
        self.status_candidate: tuple[nv.NavStatus, float] | None = None
        self.status_quarantined = False
        self.map_ack: nv.MapAck | None = None
        self.uploading_map = False
        self.map_abort_requested = False
        self.last_tx_at = -1e9
        self.poster = poster if poster is not None else BackendPoster(cfg.backend_url)
        self.perception = perception
        self.telemetry = telemetry
        self.nv_control: ControlFrame | None = None
        self.nv_control_at = -1e9
        self.nv_control_rate = RateMeter()
        self.nv_control_seen = cfg.telemetry == "nv"
        self.stop_evidence = StopEvidence()
        self.requests: queue.Queue[PendingRequest] = queue.Queue(maxsize=32)
        self.runner = TaskRunner(cfg, load_waypoints(cfg.waypoints_path), load_routes(cfg.routes_path),
                                 self._send, self._emit)
        self.prior_map: PriorMap | None = None
        self.pending_map: tuple[bytes, PriorMap] | None = None
        self.map_detail = "未下发先验地图"
        self.map_id = str(cfg.extra.get("map_id", "yuntuo_field"))
        self.field_bounds = tuple(cfg.extra.get("field_bounds", (-1.0, -3.0, 6.0, 3.0)))
        self.last_nav_post = self.last_platform_post = self.last_map_post = self.last_keepalive = -1e9
        self.nav_seq = 0
        self.public_lock = threading.Lock()
        self.public: dict = {}

    # ---------------------------------------------------------------- 线程安全入口（HTTP 线程调用）
    def submit(self, kind: str, payload: dict, timeout: float = 6.0) -> dict | None:
        req = PendingRequest(kind, payload)
        try:
            self.requests.put_nowait(req)
        except queue.Full:
            return None
        return req.response if req.ready.wait(timeout) else None

    def snapshot(self) -> dict:
        with self.public_lock:
            return dict(self.public)

    # ---------------------------------------------------------------- 主循环
    def tick(self) -> bool:
        """一次循环；返回是否有链路收发（无则调用方可小睡）"""
        now = self.clock()
        self._ensure_link(now)
        self._service_requests(now)
        if (self.pending_map is not None and self.link is not None
                and self.status_view(now).fresh and self.status.mode == 0):
            pkg, prior = self.pending_map
            self.pending_map = None
            self._upload_map(pkg, prior)
        now = self.clock()
        busy = self._io(now)
        now = self.clock()
        self.runner.on_tick(self.status_view(now), self._frame(), now)
        busy = self._io(now, recv=False) or busy
        self._publish(self.clock())
        return busy

    def _service_requests(self, now: float) -> None:
        # Bounded even if HTTP producers keep filling the queue. Also called
        # during map waits so ESTOP never waits for the whole package transfer.
        for _ in range(32):
            try:
                req = self.requests.get_nowait()
            except queue.Empty:
                break
            req.response = self._handle_request(req, now)
            req.ready.set()

    def status_view(self, now: float) -> StatusView:
        self._refresh_legacy_feedback()
        fresh = (self.status is not None and not self.status_quarantined
                 and 0 <= now-self.status_at <= self.cfg.status_timeout_s)
        age = self._control_age_us(self.stop_evidence.frame, now) if self.nv_control_seen else None
        clock_ok = fresh and (not self.nv_control_seen or age is not None and -10000 <= age <= FEEDBACK_MAX_AGE_S*1e6)
        if not self.nv_control_seen and getattr(self.telemetry, "disconnected", False):
            clock_ok = False
        return StatusView(self.status, self.status_at, fresh, self.stop_evidence.view(now, clock_ok=clock_ok))

    def _control_age_us(self, frame: ControlFrame | None, now: float) -> int | None:
        if frame is None or self.status is None:
            return None
        board_now = (self.status.t_us + int((now-self.status_at)*1e6)) & 0xFFFFFFFF
        return ((board_now-frame.raw["timestamp_ms"]*1000+0x80000000) & 0xFFFFFFFF)-0x80000000

    def _refresh_legacy_feedback(self) -> None:
        if self.nv_control_seen or self.telemetry is None:
            return
        samples = self.telemetry.drain() if hasattr(self.telemetry, "drain") else [self.telemetry.latest()]
        for frame, at in samples:
            if frame is not None:
                self.stop_evidence.ingest(frame, at)

    def _frame(self):
        return self.perception.latest() if self.perception is not None else None

    # ---------------------------------------------------------------- 链路
    def _send(self, msg: bytes, urgent: bool = False) -> None:
        if urgent:
            if msg in (nv.encode_mode("idle"), nv.encode_mode("estop")):
                self.outbox.clear()  # An older queued GOAL/TARGET must not follow a stop.
            self.outbox.appendleft(msg)
        else:
            self.outbox.append(msg)
        while len(self.outbox) > 64:
            self.outbox.pop()

    def _ensure_link(self, now: float) -> None:
        if self.link is not None or now < self.reconnect_at:
            return
        try:
            self.link = self.link_factory()
            self.link_error = None
            log.info("FPGA 导航链路已打开：%s", self.cfg.link)
        except Exception as exc:
            self.link_error = str(exc)
            self.reconnect_at = now + 3.0
            log.warning("打开 FPGA 导航链路 %s 失败：%s（3 s 后重试）", self.cfg.link, exc)

    def _drop_link(self, exc: Exception, now: float) -> None:
        log.warning("FPGA 导航链路异常：%s（2 s 后重连）", exc)
        self.link_error = str(exc)
        try:
            self.link.close()
        except Exception:
            pass
        self.link = None
        self.reconnect_at = now + 2.0
        self.outbox.clear()
        self.pending_map = None
        self.status_quarantined = True
        self.runner.fail("FPGA 链路断开，原任务中止；重连后需显式解除锁定并重新下发任务。", stop=False, now=now)

    def _transmit(self, msg: bytes) -> None:
        self.link.send(msg)
        self.last_tx_at = self.clock()

    def _io(self, now: float, recv: bool = True) -> bool:
        if self.link is None:
            return False
        busy = False
        try:
            if now - self.last_tx_at >= 0.1 and not self.outbox:
                # All transports must refresh the 250ms host lease. A heartbeat
                # never unlocks ESTOP; first connection/reconnection needs an
                # explicit operator MODE idle, rather than automatic re-arming.
                self.last_keepalive = now
                self.outbox.append(nv.encode_target(0, 0, found=False))
            while self.outbox:
                self._transmit(self.outbox.popleft())
                busy = True
            if recv:
                for i in range(4):
                    data = self.link.recv(0.02 if i == 0 else 0.0)
                    if data is None:
                        break
                    busy = True
                    self._on_message(nv.decode(data), self.clock())
        except (OSError, LinkError) as exc:
            self._drop_link(exc, now)
        return busy

    def _on_message(self, msg, now: float) -> None:
        if isinstance(msg, nv.NavStatus):
            delta = (msg.t_us-self.status.t_us) & 0xFFFFFFFF if self.status is not None else 1
            if delta == 0:
                return  # receipt is not evidence that the FPGA clock is advancing
            if delta >= 0x80000000:
                # Could be reordering, reset, or another stream. Quarantine first;
                # rebase only after the old stream expires and two advancing samples.
                candidate = self.status_candidate
                self.status_candidate = (msg, now)
                self.status_quarantined = True
                self.outbox.clear()
                self.nv_control = None
                self.nv_control_at = -1e9
                self.stop_evidence.reset()
                if candidate is None or now-self.status_at <= self.cfg.status_timeout_s:
                    return
                advance = ((msg.t_us-candidate[0].t_us) & 0xFFFFFFFF)/1e6
                elapsed = now-candidate[1]
                if not (0 < elapsed <= self.cfg.status_timeout_s and 0 < advance < self.cfg.status_timeout_s
                        and abs(advance-elapsed) <= 0.1):
                    return
                self.runner.fail("FPGA 时钟重置或状态流切换，原任务中止；请显式解除锁定后重新发起任务。", stop=False, now=now)
                self.prior_map, self.pending_map = None, None
                self.map_detail = "FPGA 已复位，先验地图缓存失效；请重新下发。"
                self.last_map_post = -1e9
            self.status_candidate, self.status_quarantined = None, False
            self.status, self.status_at = msg, now
            self.status_rate.mark(now)
            if msg.mode == 4 or msg.state == 6:
                self.outbox.clear()
                self.runner.fail("FPGA 已锁定急停，原任务中止；不会自动解除或继续任务。", stop=False, now=now)
        elif isinstance(msg, nv.MapAck):
            self.map_ack = msg
        elif isinstance(msg, ControlFrame):
            if self.status_quarantined:
                return
            if not self.nv_control_seen:
                self.stop_evidence.reset()  # never join evidence from different transports
            age = self._control_age_us(msg, now)
            clock_ok = (self.status is not None and 0 <= now-self.status_at <= self.cfg.status_timeout_s
                        and age is not None and -10000 <= age <= FEEDBACK_MAX_AGE_S*1e6)
            if not self.stop_evidence.ingest(msg, now, clock_ok=clock_ok):
                return
            self.nv_control, self.nv_control_at = msg, now
            self.nv_control_seen = True  # never fall back to a stale/mock secondary stream
            self.nv_control_rate.mark(now)

    # ---------------------------------------------------------------- 请求
    def _handle_request(self, req: PendingRequest, now: float) -> dict:
        p = req.payload
        if self.uploading_map or self.pending_map is not None:
            stopping = req.kind == "estop" or (req.kind == "mission" and p.get("command") in ("pause_task", "cancel_task"))
            if not stopping:
                return {"success": False, "data": {"accepted": False, "detail": "地图上传中，仅接受暂停、取消和急停。"}}
        if req.kind == "mission":
            command = str(p.get("command") or "")
            args = p.get("payload") if isinstance(p.get("payload"), dict) else {}
            accepted, detail = self.runner.handle_command(command, dict(args), str(p.get("source") or "web"),
                                                          self.status_view(now), now)
            if self.link is None and accepted:
                detail += "（链路暂不可用，报文已排队）"
            return {"success": True, "data": {
                "accepted": accepted, "command": command, "task_status": self.runner.task_status(),
                "current_goal": self.runner.current_goal(), "nav_state": self.runner.nav_state(),
                "received_at": _iso(), "detail": detail}}
        if req.kind == "estop":
            engage = bool(p.get("engage", True))
            if engage:
                self.outbox.clear()
                self.pending_map = None
                self.map_abort_requested = True
                self._send(nv.encode_mode("estop"), urgent=True)
                self.runner.estop()
                detail = "已请求停止运动目标并保持平衡，等待反馈确认停稳。"
            else:
                self._send(nv.encode_mode("idle"), urgent=True)
                detail = "已请求解除运行急停；旧任务不会自动恢复。"
            ok = self.link is not None
            return {"success": True, "data": {"accepted": ok, "engaged": engage,
                                              "detail": detail if ok else "FPGA 链路不在线：" + detail}}
        if req.kind == "set_pose":
            try:
                x, y, yaw = float(p["x"]), float(p["y"]), float(p.get("yaw", 0.0))
            except (KeyError, TypeError, ValueError):
                return {"success": False, "data": {"accepted": False, "detail": "需要 x、y（m）与 yaw（rad）"}}
            self._send(nv.encode_set_pose(nv.m_to_mm(x), nv.m_to_mm(y), nv.rad_to_cdeg(yaw),
                                          align=bool(p.get("align", True)),
                                          range_mm=int(float(p.get("range_m", 0)) * 1000),
                                          range_cdeg=int(float(p.get("range_deg", 0)) * 100)))
            return {"success": True, "data": {"accepted": self.link is not None,
                                              "detail": f"已下发初始位姿 ({x:.2f}, {y:.2f}, {math.degrees(yaw):.0f}°)。"}}
        if req.kind == "map":
            sv = self.status_view(now)
            if not sv.fresh or sv.status.mode != 0:
                return {"success": False, "data": {"accepted": False, "detail": "地图操作需要新鲜的FPGA空闲状态；请先显式解除导航急停。"}}
            if p.get("clear"):
                self._send(nv.encode_map_clear())
                self.prior_map = None
                self.map_detail = "已请求清除先验地图，等待FPGA无图状态。"
                self.last_map_post = -1e9
                return {"success": True, "data": {"accepted": True, "detail": self.map_detail}}
            try:
                pkg = Path(str(p["path"])).read_bytes()
                prior = parse_package(pkg)
            except (KeyError, OSError, MapPackageError) as exc:
                return {"success": False, "data": {"accepted": False, "detail": f"地图包不可用：{exc}"}}
            self.pending_map = (pkg, prior)
            if p.get("map_id"):
                self.map_id = str(p["map_id"])
            return {"success": True, "data": {"accepted": True, "detail": f"地图包校验通过（{prior.size} B），开始下发。"}}
        return {"success": False, "data": {"accepted": False, "detail": f"未知请求 {req.kind}"}}

    def load_map_file(self, path: Path) -> None:
        pkg = path.read_bytes()
        self.pending_map = (pkg, parse_package(pkg))

    def _upload_map(self, pkg: bytes, prior: PriorMap) -> bool:
        """Application ACK barrier/progress/terminal checks on every transport.

        Poll heartbeats and urgent requests during waits. A UART transport ACK
        is not proof of CPU application progress, and RECV is not terminal.
        """
        t0 = self.clock()
        self.uploading_map, self.map_abort_requested = True, False
        self.map_detail = f"正在下发先验地图（{prior.size} B）。"
        def exchange(message: bytes, accept) -> nv.MapAck:
            for _ in range(21):
                self._transmit(message)
                ack = self._wait_map_ack(0.35, 1, accept=accept)
                if ack is not None:
                    return ack
            raise LinkError("地图应用应答超时（已完成有界重发）")
        try:
            self.map_ack = None
            exchange(nv.encode_map_begin(len(pkg)), lambda a: a.map_state == 1 and a.next_offset == 0)
            self.prior_map = None
            off = 0
            while off < len(pkg):
                end = min(off + nv.MAP_CHUNK, len(pkg))
                ack = exchange(nv.encode_map_data(off, pkg[off:end]), lambda a: a.map_state in (3, 4)
                               or (a.map_state == 1 and a.next_offset == end))
                if ack.map_state in (3, 4):
                    self.map_detail = f"地图在偏移{off}被FPGA拒绝：{ack.map_state_name}"
                    return False
                off = end
            ack = exchange(nv.encode_map_end(), lambda a: a.map_state in (2, 3, 4))
        except MapUploadAborted:
            self.map_detail = "地图上传已因急停中止。"
            return False
        except (OSError, LinkError) as exc:
            self.map_detail = f"地图下发失败：{exc}"
            self._drop_link(exc, self.clock())
            return False
        finally:
            self.uploading_map = False
        ok = ack.map_state == 2 and ack.next_offset == len(pkg)
        self.map_detail = (f"先验地图已加载（{prior.size} B，{self.clock() - t0:.1f} s），请下发初始位姿对准"
                           if ok else f"地图下发后板上状态：{ack.map_state_name if ack else '无应答'}")
        log.info(self.map_detail)
        if ok:
            self.prior_map = prior
            self.last_map_post = -1e9
        return ok

    def _wait_map_ack(self, timeout: float, tries: int, *, accept) -> nv.MapAck | None:
        deadline = self.clock() + timeout * tries
        while self.clock() < deadline:
            self._service_requests(self.clock())
            self._io(self.clock(), recv=False)
            if self.map_abort_requested:
                raise MapUploadAborted()
            if self.link is None:
                raise LinkError("地图上传期间链路断开")
            data = self.link.recv(min(0.025, max(0.0, deadline-self.clock())))
            msg = nv.decode(data) if data else None
            self._on_message(msg, self.clock())
            self._publish(self.clock())
            if isinstance(msg, nv.MapAck) and accept(msg):
                return msg
        return None

    # ---------------------------------------------------------------- 上送后端
    def _emit(self, payload: dict) -> None:
        self.poster.post_event("/api/internal/mission/update", payload)

    def _publish(self, now: float) -> None:
        sv = self.status_view(now)
        if sv.fresh and self.status_at > self.last_nav_post and now - self.last_nav_post >= 1.0 / self.cfg.nav_post_hz:
            self.last_nav_post = now
            self.poster.post_latest("nav", "/api/internal/navigation/state", self.navigation_snapshot(now))
        if now - self.last_platform_post >= 1.0 / self.cfg.platform_post_hz:
            self.last_platform_post = now
            platform = self.platform_status(now)
            self.poster.post_latest("platform", "/api/internal/platform/status", {"platform_status": platform})
            with self.public_lock:
                self.public = {
                    "status": "ok", "service": "yuntuo-fpga-bridge", "link": self.cfg.link,
                    "link_open": self.link is not None, "link_error": self.link_error,
                    "status_age_s": round(now - self.status_at, 2) if self.status else None,
                    "map": self.map_detail, "task": self.runner.task_status(), "platform": platform,
                    "updated_at": _iso(),
                }
        if now - self.last_map_post >= 10.0:      # 后端重启后地图缓存会丢，定期重发（10 cm 栅格，十几 KB）
            self.last_map_post = now
            self.poster.post_latest("map", "/api/internal/navigation/map", self.map_payload())

    def navigation_snapshot(self, now: float) -> dict:
        s = self.status
        self.nav_seq += 1
        task = self.runner.task
        nav_state = self.runner.nav_state()
        if s.state == 6:
            nav_state = "failed"
        goal = None
        if s.mode in (1, 2, 3):
            goal = {"x": s.goal_x_mm / 1000, "y": s.goal_y_mm / 1000, "yaw": 0.0}
        target = None
        pick = self.runner.target_pick(now)
        if pick is not None:
            c, sn = math.cos(s.yaw_rad), math.sin(s.yaw_rad)
            target = {"x": round(s.x_mm / 1000 + c * pick.x_m - sn * pick.y_m, 3),
                      "y": round(s.y_mm / 1000 + sn * pick.x_m + c * pick.y_m, 3)}
        remaining = task.remaining_m if task is not None and task.active else None
        return {
            "source": "fpga_bridge", "frame_id": "map", "timestamp": utc_now(), "sequence": self.nav_seq,
            "map_version": self.prior_map.digest if self.prior_map else "canvas",
            "pose": {"x": s.x_mm / 1000, "y": s.y_mm / 1000, "yaw": s.yaw_rad},
            "goal": goal,
            "velocity": {"vx": s.vx_mmps / 1000, "vy": 0.0, "wz": s.wz_mradps / 1000},
            "global_path": [], "local_path": [], "nav_state": nav_state,
            "remaining_distance": round(remaining, 3) if remaining is not None else None,
            "target": target,
        }

    def map_payload(self) -> dict:
        if self.prior_map is not None:
            m = self.prior_map
            return {"map_id": self.map_id, "version": m.digest, "frame_id": "map", "timestamp": utc_now(),
                    "resolution": 0.1, "width": m.width, "height": m.height,
                    "origin": {"x": m.origin_x_m, "y": m.origin_y_m, "yaw": 0.0}, "data": m.occupancy()}
        x0, y0, x1, y1 = self.field_bounds
        w, h = max(1, int(round((x1 - x0) / 0.1))), max(1, int(round((y1 - y0) / 0.1)))
        return {"map_id": self.map_id, "version": f"canvas-{x0:g}_{y0:g}_{x1:g}_{y1:g}", "frame_id": "map",
                "timestamp": utc_now(), "resolution": 0.1, "width": w, "height": h,
                "origin": {"x": x0, "y": y0, "yaw": 0.0}, "data": [-1] * (w * h)}

    def platform_status(self, now: float) -> dict:
        sv = self.status_view(now)
        s = self.status if sv.fresh else None
        online = "mock" if self.cfg.link_is_mock else "online"
        out: dict[str, Any] = {
            "source": "fpga_bridge", "updated_at": utc_now(),
            "nav_link": online if sv.fresh else "offline", "nav_link_kind": self.cfg.link,
            "fpga_mode": s.mode_name if s else None, "fpga_state": s.state_name if s else None,
            "loc_state": s.loc_name if s else None,
            "loc_quality": max(0, min(100, s.loc_quality)) if s and s.loc_state else None,
            # MAP_ACK READY precedes SET_POSE; LOC_ODOM until alignment starts
            # does not undo the acknowledged map transfer.
            "map_loaded": bool(s and (self.prior_map is not None or s.loc_state)),
            "target_valid": bool(s and s.target_valid),
            "lidar_ok": s.lidar_ok if s else None, "odom_ok": s.odom_ok if s else None,
            "cmd_vx_mps": s.vx_mmps / 1000 if s else None, "cmd_wz_radps": s.wz_mradps / 1000 if s else None,
            "fpga_uptime_s": s.t_us / 1e6 if s else None,
            "status_rate_hz": round(self.status_rate.rate(now), 2),
            "control_link": "unknown", "policy_active": None, "control_estop": None, "control_faults": [],
            "wheel_left_mps": None, "wheel_right_mps": None, "roll_deg": None, "pitch_deg": None,
            "yaw_rate_radps": None, "height_cmd_m": None, "telemetry_rate_hz": None,
            "control_telemetry": None,
        }
        age_us = None
        if self.nv_control_seen:
            frame, at = self.nv_control, self.nv_control_at
            fresh = frame is not None and now-at <= 1.0 and self.status_view(now).fresh
            if fresh:
                # Both timestamps originate from the same FPGA reset/50MHz clock.
                # Convert modulo the STATUS 32-bit microsecond timer, including wrap.
                age_us = self._control_age_us(frame, now)
                fresh = -100000 <= age_us <= 1000000
            rate = self.nv_control_rate.rate(now)
        else:
            if self.telemetry is None:
                return out
            frame, at = self.stop_evidence.frame, self.stop_evidence.received_at
            fresh = (frame is not None and 0 <= now-at <= 1.0
                     and not getattr(self.telemetry, "disconnected", False))
            rate = self.telemetry.rate.rate(now)
        out["control_link"] = (online if fresh else "offline")
        out["telemetry_rate_hz"] = round(rate, 1)
        if frame is not None:
            out["control_telemetry"] = {
                "transport": "nv_udp" if self.nv_control_seen else "legacy_telemetry",
                "source": "mock" if self.cfg.link_is_mock else "fpga",
                "version": frame.version, "fresh": bool(fresh),
                "receive_age_ms": max(0, round((now-at)*1000, 1)),
                "measurement_age_ms": round(age_us/1000, 1) if age_us is not None else None,
                "raw": dict(frame.raw),
            }
        if fresh:
            out.update({
                "policy_active": frame.active, "control_estop": frame.stop_latched, "control_faults": frame.faults(),
                "wheel_left_mps": frame.wheel_left_mps, "wheel_right_mps": frame.wheel_right_mps,
                "roll_deg": frame.roll_deg, "pitch_deg": frame.pitch_deg, "yaw_rate_radps": frame.yaw_rate_radps,
                "height_cmd_m": frame.height_cmd,
            })
        return out
