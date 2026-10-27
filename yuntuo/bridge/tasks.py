"""任务状态机：网页 / 语音任务 -> NV 报文，FPGA STATUS -> 任务事件。

定点类（go_to_waypoint / return_home / start_patrol）：逐点发 GOAL，STATUS.state=arrived 且目标点一致才算到达；
  巡检点之间按路线 stop_seconds 停留；受阻持续超过 blocked_fail_s 判失败。
目标类（search_target / follow_target）：发 MODE search，感知结果经筛选后以 TARGET 报文持续下发，FPGA 自主
  探索 -> 发现即跟踪 -> 停在目标前 0.7 m；search_target 稳定停在目标附近即完成，follow_target 一直跟到取消或超时。
暂停 / 取消请求 MODE idle，业务状态与反馈停稳分开；上下文留在本进程，恢复时重发。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from yuntuo.bridge.config import BridgeConfig, Waypoint
from yuntuo.bridge.inputs import DetectionFrame
from yuntuo.bridge.feedback import MotionView, STOP_HOLD_S, STOP_V_MMPS, STOP_W_MRADPS
from yuntuo.bridge.targets import TargetPick, TargetSpec, pick_target
from yuntuo.fpga_link import nv_proto as nv

log = logging.getLogger("fpga_bridge")

GOTO_TYPES = {"go_to_waypoint", "return_home", "start_patrol"}
TARGET_TYPES = {"search_target", "follow_target"}
ACTIVE_STATES = {"pending", "running", "paused"}
STANDOFF_M = 0.7


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StatusView:
    status: nv.NavStatus | None
    received_at: float          # 本机单调时钟
    fresh: bool
    motion: MotionView = field(default_factory=MotionView)


@dataclass
class Task:
    task_id: str
    task_type: str
    source: str
    state: str = "pending"
    phase: str = "starting"
    detail: str = ""
    progress: int = 0
    points: list[Waypoint] = field(default_factory=list)
    index: int = 0
    stop_seconds: float = 0.0
    dwell_until: float | None = None
    spec: TargetSpec | None = None
    deadline: float | None = None
    timeout_s: float = 0.0
    paused_at: float | None = None
    started_at: float = 0.0
    sent_at: float = 0.0
    sent_goal: tuple[int, int] | None = None
    confirmed: bool = False
    resend: int = 0
    started_emitted: bool = False
    leg_start_m: float | None = None
    remaining_m: float | None = None
    blocked_since: float | None = None
    lost_since: float | None = None
    near_since: float | None = None
    near_track: int | None = None
    arrival_wait_since: float | None = None
    stop_requested_at: float | None = None
    finish_after_stop: str | None = None
    locked_track: int | None = None
    last_pick: TargetPick | None = None
    last_pick_at: float = -1e9
    track_start_m: float | None = None
    last_target_seq: float | None = None      # 已处理的检测帧（按接收时刻区分）
    last_target_sent: float = -1e9
    last_progress_emit: float = -1e9
    last_verify_emit: float = -1e9
    event_seq: int = 0

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def current_point(self) -> Waypoint | None:
        return self.points[self.index] if self.points and self.index < len(self.points) else None


class TaskRunner:
    def __init__(self, cfg: BridgeConfig, waypoints: dict[str, Waypoint], routes: dict[str, dict],
                 send: Callable[[bytes, bool], None], emit: Callable[[dict], None]) -> None:
        self.cfg = cfg
        self.waypoints = waypoints
        self.routes = routes
        self.send = send            # send(msg, urgent)
        self.emit_payload = emit
        self.task: Task | None = None
        self.now = 0.0

    # ---------------------------------------------------------------- 对外视图
    def task_status(self) -> dict:
        t = self.task
        if t is None:
            return {"task_id": "fpga-idle", "task_type": "placeholder", "state": "idle", "progress": 0,
                    "source": "fpga_bridge", "phase": "idle", "current_waypoint_id": None,
                    "waypoint_index": None, "waypoint_count": None, "detail": "等待任务。", "updated_at": utc_now()}
        point = t.current_point
        return {
            "task_id": t.task_id, "task_type": t.task_type, "state": t.state, "progress": int(t.progress),
            "source": "fpga_bridge", "phase": t.phase,
            "current_waypoint_id": point.waypoint_id if point else None,
            "waypoint_index": t.index if t.points else None,
            "waypoint_count": len(t.points) if t.points else None,
            "detail": t.detail, "updated_at": utc_now(),
        }

    def current_goal(self) -> str | None:
        t = self.task
        if t is None:
            return None
        if t.spec is not None:
            return f"target:{t.spec.label}"
        point = t.current_point
        return point.waypoint_id if point else None

    def nav_state(self, state: str | None = None) -> str:
        value = state or (self.task.state if self.task else "idle")
        return {"running": "running", "pending": "running", "paused": "paused", "completed": "completed",
                "failed": "failed"}.get(value, "idle")

    def target_pick(self, now: float, max_age_s: float = 1.0) -> TargetPick | None:
        t = self.task
        if t is None or t.last_pick is None or now - t.last_pick_at > max_age_s:
            return None
        return t.last_pick

    # ---------------------------------------------------------------- 事件
    def _emit(self, event_type: str, detail: str, suffix: str = "") -> None:
        t = self.task
        if t is None:
            return
        t.detail = detail
        t.event_seq += 1
        point = t.current_point
        wid = point.waypoint_id if point else None
        payload = {
            "event": {
                "event_id": f"{t.task_id}:{event_type}:{suffix or t.event_seq}",
                "task_id": t.task_id, "event_type": event_type, "task_state": t.state, "detail": detail,
                "source": "fpga_bridge", "waypoint_id": wid,
                "remaining_distance": round(t.remaining_m, 3) if t.remaining_m is not None else None,
                "progress": int(t.progress), "timestamp": utc_now(),
            },
            "task_status": self.task_status(),
            "current_goal": self.current_goal(),
            "nav_state": self.nav_state(),
        }
        self.emit_payload(payload)

    def _end(self, state: str, event_type: str, detail: str, stop: bool = True) -> None:
        t = self.task
        if t is None:
            return
        if stop:
            self.send(nv.encode_mode("idle"), True)
        t.finish_after_stop = None
        if not stop:
            t.stop_requested_at = None
        t.state, t.phase = state, state
        if stop:
            t.phase, t.stop_requested_at = "waiting_stop", self.now
            detail += " 已请求 FPGA 停止，停稳尚未确认。"
        if state == "completed":
            t.progress = 100
        t.dwell_until = None
        self._emit(event_type, detail)
        log.info("任务 %s %s：%s", t.task_id, state, detail)

    def fail(self, detail: str, stop: bool = True, *, now: float | None = None) -> None:
        if now is not None:
            self.now = now
        if self.task is not None and self.task.active:
            self._end("failed", "failed", detail, stop)

    # ---------------------------------------------------------------- 命令
    def handle_command(self, command: str, args: dict, source: str, sv: StatusView, now: float) -> tuple[bool, str]:
        self.now = now
        if command == "pause_task":
            return self._pause(now)
        if command == "resume_task":
            return self._resume(sv, now)
        if command == "cancel_task":
            return self._cancel()
        if command not in GOTO_TYPES | TARGET_TYPES:
            return False, f"不支持的任务命令：{command}"
        if self.task is not None and self.task.active:
            return False, "已有活动任务，请先取消当前任务。"
        problem = self._preflight(sv, command in GOTO_TYPES)
        if problem:
            return False, problem
        if command in GOTO_TYPES:
            return self._start_goto(command, args, source, now)
        return self._start_target(command, args, source, now)

    def _preflight(self, sv: StatusView, is_goto: bool) -> str | None:
        s = sv.status
        if s is None or not sv.fresh:
            return f"FPGA 导航状态不在线（超过 {self.cfg.status_timeout_s:.1f} s 未收到 STATUS）。"
        if s.state == 6 or s.mode == 4:
            return "FPGA 导航处于急停，请先解除急停。"
        loc = s.loc_state or 0
        if loc == 0 and is_goto and not self.cfg.allow_mapless_goto:
            return "FPGA 未加载先验地图，地图坐标点位不可用。"
        if loc in (1, 4) and self.cfg.require_localization:
            return f"有图定位未就绪（{nv.LOC_LABELS.get(loc)}），请先下发初始位姿完成对准。"
        return None

    def _start_goto(self, command: str, args: dict, source: str, now: float) -> tuple[bool, str]:
        try:
            if command == "go_to_waypoint":
                ids, stop_s = [str(args["waypoint_id"])], 0.0
            elif command == "return_home":
                ids, stop_s = ["home"], 0.0
            else:
                route_id = str(args.get("patrol_id") or args.get("route_id") or "default_patrol")
                route = self.routes.get(route_id)
                if not route or not route.get("enabled", True):
                    raise ValueError(f"巡检路线不存在或已禁用：{route_id}")
                ids = [str(w) for w in route["waypoints"]] + (["home"] if route.get("return_home") else [])
                stop_s = float(route.get("stop_seconds", 0) or 0)
            points = []
            for wid in ids:
                if wid not in self.waypoints:
                    raise ValueError(f"目标点不存在、已禁用或未配置坐标：{wid}")
                points.append(self.waypoints[wid])
        except (KeyError, ValueError) as exc:
            return False, str(exc).strip("'")
        self.task = Task(task_id=f"fpga-{command.replace('_', '-')}-{uuid4().hex[:10]}", task_type=command,
                         source=source, points=points, stop_seconds=stop_s, started_at=now)
        self._send_goal(now)
        return True, f"已向 FPGA 下发目标点：{points[0].name}。"

    def _start_target(self, command: str, args: dict, source: str, now: float) -> tuple[bool, str]:
        spec = TargetSpec(str(args.get("target_class") or "person"), args.get("color"), str(args.get("label") or ""))
        timeout_s = float(args.get("timeout_s") or (300 if command == "follow_target" else 180))
        self.task = Task(task_id=f"fpga-{command.replace('_', '-')}-{uuid4().hex[:10]}", task_type=command,
                         source=source, spec=spec, timeout_s=timeout_s, deadline=now + timeout_s, started_at=now)
        t = self.task
        t.state, t.phase, t.sent_at = "running", "searching", now
        self.send(nv.encode_mode("search"), False)
        verb = "跟随" if command == "follow_target" else "寻找"
        self._emit("started", f"开始{verb}「{spec.label}」：FPGA 进入探索模式。")
        return True, f"已开始{verb}「{spec.label}」。"

    def _send_goal(self, now: float) -> None:
        t = self.task
        p = t.current_point
        gx, gy = nv.m_to_mm(p.x), nv.m_to_mm(p.y)
        yaw = nv.rad_to_cdeg(p.yaw) if self.cfg.send_goal_yaw else nv.YAW_DONT_CARE
        self.send(nv.encode_goal(gx, gy, yaw), False)
        t.sent_goal, t.sent_at, t.confirmed = (gx, gy), now, False
        t.near_since = t.arrival_wait_since = None
        t.leg_start_m, t.blocked_since = None, None
        t.state = "pending" if not t.started_emitted else "running"
        t.phase, t.detail = "sending_goal", f"正在前往{p.name}。"

    def _pause(self, now: float) -> tuple[bool, str]:
        t = self.task
        if t is None or not t.active:
            return False, "当前没有可暂停的活动任务。"
        if t.finish_after_stop is not None:
            return False, "跟随时长已结束，正在等待停稳确认；可取消，不能暂停或恢复。"
        if t.state == "paused":
            return True, "任务已经处于暂停状态。"
        self.send(nv.encode_mode("idle"), True)
        t.state, t.phase, t.paused_at = "paused", "waiting_stop", now
        t.stop_requested_at = now
        t.near_since = t.blocked_since = None
        self._emit("paused", "任务已暂停；已请求 FPGA 停止，等待反馈确认停稳。")
        return True, t.detail

    def _resume(self, sv: StatusView, now: float) -> tuple[bool, str]:
        t = self.task
        if t is None or t.state != "paused":
            return False, "当前没有可恢复的暂停任务。"
        problem = self._preflight(sv, t.task_type in GOTO_TYPES)
        if problem:
            return False, problem
        if t.deadline is not None and t.paused_at is not None:
            t.deadline += now - t.paused_at
        t.paused_at = None
        t.stop_requested_at = t.finish_after_stop = t.near_since = t.arrival_wait_since = None
        t.state = "running"
        if t.task_type in GOTO_TYPES:
            if t.dwell_until is not None:
                t.dwell_until = now
                t.phase = "dwell"
            else:
                self._send_goal(now)
                t.state = "running"
        else:
            t.phase, t.confirmed, t.resend, t.sent_at = "searching", False, 0, now
            self.send(nv.encode_mode("search"), False)
        self._emit("resumed", "任务已恢复。")
        return True, "任务已恢复。"

    def _cancel(self) -> tuple[bool, str]:
        t = self.task
        if t is None or not t.active:
            return False, "当前没有可取消的活动任务。"
        self._end("cancelled", "cancelled", "任务已取消。")
        return True, t.detail

    def estop(self) -> None:
        """急停由 core 直接下发 MODE estop；这里只结束任务"""
        if self.task is not None and self.task.active:
            self._end("failed", "failed", "急停触发，任务中止。", stop=False)

    # ---------------------------------------------------------------- 周期
    def on_tick(self, sv: StatusView, frame: DetectionFrame | None, now: float) -> None:
        self.now = now
        t = self.task
        if t is not None and t.phase == "waiting_stop":
            self._tick_stop(sv, now)
            return
        if t is None or t.state not in ("pending", "running"):
            return
        if not sv.fresh or sv.status is None:
            t.near_since = None
            if t.lost_since is None:
                t.lost_since = now
                t.detail = "FPGA 导航状态中断，等待恢复。"
            elif now - t.lost_since > self.cfg.link_loss_fail_s:
                self.fail(f"FPGA 导航链路中断超过 {self.cfg.link_loss_fail_s:.0f} s，任务中止。", stop=False)
            return
        t.lost_since = None
        if t.task_type in GOTO_TYPES:
            self._tick_goto(sv, now)
        else:
            self._tick_target(sv, frame, now)

    def _tick_stop(self, sv: StatusView, now: float) -> None:
        t, s = self.task, sv.status
        since = t.stop_requested_at
        m = sv.motion
        confirmed = (sv.fresh and s is not None and sv.received_at > since and s.mode == 0
                     and abs(s.vx_mmps) <= STOP_V_MMPS and abs(s.wz_mradps) <= STOP_W_MRADPS
                     and m.stopped and m.quiet_since is not None
                     and now-max(since, m.quiet_since) >= STOP_HOLD_S
                     and sv.received_at-since >= STOP_HOLD_S)
        if confirmed:
            t.stop_requested_at = None
            if t.finish_after_stop:
                detail, t.finish_after_stop = t.finish_after_stop, None
                self._end("completed", "completed", detail + " 反馈已满足停稳条件。", stop=False)
            else:
                t.phase = t.state
                self._emit("progress", {"paused": "任务已暂停", "cancelled": "任务已取消",
                                        "failed": "任务已中止"}.get(t.state, "已请求停止") + "；反馈已满足停稳条件。")
        elif now-since > self.cfg.link_loss_fail_s:
            t.phase = "stop_unconfirmed"
            if t.finish_after_stop:
                t.state, t.finish_after_stop = "failed", None
                self._emit("failed", "跟随时长已结束，但未能确认停稳；请检查控制反馈。")
            else:
                self._emit("progress", "停止已请求，但未能确认停稳；请检查控制反馈。")

    def _arrival_ready(self, sv: StatusView, now: float, hold_s: float) -> bool:
        t, m = self.task, sv.motion
        if t.near_since is None:
            t.near_since = now
        self._verification_detail(f"到达条件待核验：{m.reason}。", now)
        return (m.stopped and m.quiet_since is not None
                and now-max(t.near_since, m.quiet_since) >= hold_s
                and sv.received_at-t.near_since >= hold_s)

    def _verification_detail(self, detail: str, now: float) -> None:
        t = self.task
        entering = t.phase != "verifying_arrival"
        t.phase, t.detail = "verifying_arrival", detail
        if entering or now-t.last_verify_emit >= 1.0:
            t.last_verify_emit = now
            self._emit("progress", detail)

    def _tick_goto(self, sv: StatusView, now: float) -> None:
        t, s = self.task, sv.status
        if t.dwell_until is not None:
            if now >= t.dwell_until:
                t.dwell_until = None
                self._send_goal(now)
            return
        point = t.current_point
        if t.confirmed and (abs(s.goal_x_mm-t.sent_goal[0]) > 30 or abs(s.goal_y_mm-t.sent_goal[1]) > 30):
            self.fail("FPGA 当前目标与本任务目标不一致，任务中止。")
            return
        if not t.confirmed:
            gx, gy = t.sent_goal
            same_goal = abs(s.goal_x_mm - gx) <= 30 and abs(s.goal_y_mm - gy) <= 30
            if sv.received_at >= t.sent_at + 0.25 and same_goal and (s.mode == 1 or s.state == 2):
                t.confirmed, t.state, t.phase = True, "running", "navigating"
                t.leg_start_m = max(0.01, s.distance_to_goal_mm() / 1000)
                if not t.started_emitted:
                    t.started_emitted = True
                    self._emit("started", f"FPGA 已受理目标点，前往{point.name}。")
                else:
                    self._emit("progress", f"前往{point.name}。")
            elif now - t.sent_at > self.cfg.goal_confirm_s:
                if t.resend >= 3:
                    self.fail("FPGA 未确认目标点（已重发 3 次）。")
                    return
                t.resend += 1
                self._send_goal(now)
            return
        if s.state != 2 or s.mode != 0:
            t.near_since = t.arrival_wait_since = None
        if s.state == 2 and s.mode == 0:
            if math.hypot(s.x_mm-t.sent_goal[0], s.y_mm-t.sent_goal[1]) > self.cfg.goto_arrive_tol_m*1000:
                self.fail("FPGA 报告到达，但估计位置仍超出目标容差。")
                return
            if t.arrival_wait_since is None:
                t.arrival_wait_since = now
            eligible = (abs(s.vx_mmps) <= STOP_V_MMPS and abs(s.wz_mradps) <= STOP_W_MRADPS
                        and s.odom_ok and not self._preflight(sv, True))
            if eligible and self._arrival_ready(sv, now, STOP_HOLD_S):
                self._arrived(now)
            elif now-t.arrival_wait_since > self.cfg.link_loss_fail_s:
                self.fail("FPGA 报告到达，但位置/指令/反馈停稳条件未能确认。")
            elif not eligible:
                t.near_since = None
                self._verification_detail("到达条件待核验：位置、定位质量或停止指令未满足。", now)
        elif s.state == 6:
            self.fail("FPGA 急停，任务中止。", stop=False)
        elif s.state == 3:
            if t.blocked_since is None:
                t.blocked_since = now
                t.phase = "blocked"
                self._emit("blocked", "前方受阻，FPGA 正在重新规划。")
            elif now - t.blocked_since > self.cfg.blocked_fail_s:
                self.fail(f"受阻超过 {self.cfg.blocked_fail_s:.0f} s，无法到达{point.name}。")
        elif s.mode != 1:
            self.fail(f"FPGA 当前任务被外部改变（模式 {s.mode_name}，状态 {s.state_name}）。", stop=False)
        else:
            t.near_since = t.arrival_wait_since = None
            if t.blocked_since is not None:
                t.blocked_since, t.phase = None, "navigating"
            self._update_progress(s.distance_to_goal_mm() / 1000, now)

    def _update_progress(self, remaining_m: float, now: float) -> None:
        t = self.task
        t.remaining_m = remaining_m
        if t.leg_start_m is None or remaining_m > t.leg_start_m:
            t.leg_start_m = max(remaining_m, 0.01)
        leg = max(0.0, min(0.99, 1.0 - remaining_m / t.leg_start_m))
        n = max(1, len(t.points))
        t.progress = min(99, int((t.index + leg) / n * 100))
        if now - t.last_progress_emit >= 1.0:
            t.last_progress_emit = now
            self._emit("progress", f"前往{t.current_point.name}，剩余 {remaining_m:.2f} m。", suffix=f"p{t.event_seq}")

    def _arrived(self, now: float) -> None:
        t = self.task
        point = t.current_point
        t.remaining_m = 0.0
        t.progress = min(99, int((t.index + 1) / max(1, len(t.points)) * 100))
        self._emit("arrived", f"已到达{point.name}。", suffix=f"{t.index}-{point.waypoint_id}")
        if t.index + 1 < len(t.points):
            t.index += 1
            t.phase = "dwell"
            t.detail = f"在{point.name}停留 {t.stop_seconds:.0f} s。"
            t.dwell_until = now + t.stop_seconds
            return
        self._end("completed", "completed", "导航任务已完成。", stop=False)

    def _tick_target(self, sv: StatusView, frame: DetectionFrame | None, now: float) -> None:
        t, s = self.task, sv.status
        if s.state == 6:
            self.fail("FPGA 急停，任务中止。", stop=False)
            return
        if t.deadline is not None and now > t.deadline:
            if t.task_type == "follow_target":
                self.send(nv.encode_mode("idle"), True)
                t.phase, t.stop_requested_at = "waiting_stop", now
                t.finish_after_stop = f"跟随「{t.spec.label}」达到时长上限。"
                self._emit("progress", t.finish_after_stop + " 已请求停止，等待反馈确认停稳。")
            else:
                self.fail(f"{t.timeout_s:.0f} s 内未找到「{t.spec.label}」。")
            return
        if not t.confirmed:
            if sv.received_at >= t.sent_at + 0.25 and s.mode in (2, 3):
                t.confirmed = True
            elif now - t.sent_at > self.cfg.goal_confirm_s:
                if t.resend >= 3:
                    self.fail("FPGA 未进入探索模式（已重发 3 次）。")
                    return
                t.resend += 1
                t.sent_at = now
                self.send(nv.encode_mode("search"), False)
            return
        if s.mode not in (2, 3):
            self.fail(f"FPGA 当前任务被外部改变（模式 {s.mode_name}），目标任务中止。", stop=False)
            return
        self._forward_target(frame, now)
        tracking = s.mode == 2 and s.target_valid
        phase = "tracking" if tracking else "searching"
        if phase != t.phase and not (tracking and t.phase == "verifying_arrival"):
            t.phase = phase
            t.near_since = None
            if tracking:
                pick = t.last_pick
                dist = f"，距离约 {pick.distance_m:.1f} m" if pick else ""
                self._emit("target_found", f"发现「{t.spec.label}」{dist}，FPGA 开始接近。")
                t.track_start_m = pick.distance_m if pick else None
            else:
                self._emit("target_lost", f"「{t.spec.label}」不在视野内，FPGA 继续探索。")
        if not tracking:
            t.progress = max(t.progress, 5)
            return
        pick = self.target_pick(now, 0.8)
        if pick is not None:
            t.remaining_m = max(0.0, pick.distance_m - STANDOFF_M)
            if not t.track_start_m:
                t.track_start_m = pick.distance_m
            span = max(0.05, t.track_start_m - STANDOFF_M)
            t.progress = max(t.progress, min(95, 30 + int(65 * (1 - t.remaining_m / span))))
            if now - t.last_progress_emit >= 1.0:
                t.last_progress_emit = now
                self._emit("progress", f"接近「{t.spec.label}」，距离 {pick.distance_m:.2f} m。", suffix=f"p{t.event_seq}")
        if t.task_type != "search_target":
            return
        near_goal = s.distance_to_goal_mm() / 1000 <= self.cfg.target_arrive_tol_m
        near_target = pick is not None and pick.distance_m <= self.cfg.target_arrive_dist_m
        if (near_goal and near_target and s.odom_ok and not self._preflight(sv, False)
                and abs(s.vx_mmps) <= STOP_V_MMPS and abs(s.wz_mradps) <= STOP_W_MRADPS):
            if t.near_track != pick.track_id:
                t.near_since, t.near_track = None, pick.track_id
            if self._arrival_ready(sv, now, max(STOP_HOLD_S, self.cfg.arrive_hold_s)):
                t.remaining_m = 0.0
                self._emit("arrived", f"已到达「{t.spec.label}」附近（约 {pick.distance_m:.2f} m）。", suffix="target")
                self.send(nv.encode_mode("idle"), True)
                self._end("completed", "completed", f"已找到「{t.spec.label}」，反馈已满足停稳条件。", stop=False)
        else:
            t.near_since = None

    def _forward_target(self, frame: DetectionFrame | None, now: float) -> None:
        """新的一帧检测里有匹配目标就发 TARGET（限速；超过最大时延的帧丢弃，FPGA 按 latency 回查历史位姿）"""
        t = self.task
        if frame is None or frame.received_mono == t.last_target_seq:
            return
        if now - t.last_target_sent < 1.0 / max(1.0, self.cfg.target_rate_hz):
            return
        t.last_target_seq = frame.received_mono
        latency = frame.latency_ms(now)
        if latency > self.cfg.target_max_latency_ms:
            return
        pick = pick_target(frame, t.spec, t.locked_track)
        if pick is None or not 0.15 <= pick.distance_m <= 8.0:
            return
        t.locked_track = pick.track_id or None
        t.last_pick, t.last_pick_at = pick, now
        self.send(nv.encode_target(nv.m_to_mm(pick.x_m), nv.m_to_mm(pick.y_m), nv.m_to_mm(pick.z_m), found=True,
                                   cls=t.spec.cls_code, conf_permille=int(pick.conf * 1000),
                                   latency_ms=int(latency), track_id=pick.track_id), False)
        t.last_target_sent = now
