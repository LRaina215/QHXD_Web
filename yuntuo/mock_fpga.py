"""FPGA 导航模拟器：说 NV 协议的"假 FPGA"，用于 RK3588 端在不上机的情况下联调网页、fpga_bridge 与任务流程。

  python -m yuntuo.mock_fpga                              UDP 127.0.0.1:9000，5 Hz STATUS
  python -m yuntuo.mock_fpga --camera-udp 127.0.0.1:9102  同时扮演相机：把视野内的虚拟物体按感知节点的格式发给 fpga_bridge
  python -m yuntuo.mock_fpga --telemetry-udp 127.0.0.1:9104   同时模拟底盘控制 V2 遥测
  python -m yuntuo.mock_fpga --with-map                   假装已加载先验地图且定位正常

模拟的行为与固件语义一致（fw/nav/nav_task.c）：GOAL 到达后 mode 回 idle、state=arrived；WAYPOINTS 中间点途经；
SEARCH 收到 found=1 的 TARGET 自动转 TRACK，接近到站位距离 0.7 m 后原地转向面对目标（跟踪没有 arrived 状态）；
目标 1.5 s 未更新回到 SEARCH；found=0 被忽略；ESTOP 零速，MODE idle 解除。
运动学只是差速小车 + 比例控制，不模拟避障与地形。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import socket
import time
from dataclasses import dataclass, field

from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link import telemetry as tm
from yuntuo.fpga_link.nvmp import MapPackageError, parse_package

TARGET_TIMEOUT_S = 1.5
STANDOFF_M = 0.7
TRACK_HOLD_M = 0.15
GOAL_TOL_M = 0.15
WP_TOL_M = 0.30
V_MAX = 0.5
W_MAX = 1.2
TRACK_WIDTH_M = 0.40


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


@dataclass
class WorldObject:
    cls: str
    color: str | None
    x: float
    y: float
    z: float = 0.1
    orbit: tuple[float, float, float, float] | None = None   # (cx, cy, r, w) 绕圈运动（模拟行人）

    def position(self, t: float) -> tuple[float, float]:
        if self.orbit is None:
            return self.x, self.y
        cx, cy, r, w = self.orbit
        return cx + r * math.cos(w * t), cy + r * math.sin(w * t)


def default_world() -> list[WorldObject]:
    return [
        WorldObject("bottle", "red", 3.6, 1.3, 0.10),
        WorldObject("bottle", "blue", 1.6, -1.7, 0.10),
        WorldObject("person", None, 3.0, -1.0, 0.85, orbit=(3.0, -0.6, 0.6, 0.12)),
    ]


@dataclass
class MockFpgaCore:
    bounds: tuple[float, float, float, float] = (-0.5, -2.5, 5.0, 2.5)
    with_map: bool = False
    seed: int = 7
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    vx: float = 0.0
    wz: float = 0.0
    mode: int = 0
    state: int = 0
    goal: tuple[float, float] = (0.0, 0.0)
    wps: list[tuple[float, float]] = field(default_factory=list)
    wp_i: int = 0
    wp_loop: bool = False
    target: tuple[float, float] | None = None
    target_t: float = -1e9
    target_id: int = 0
    search_goal: tuple[float, float] | None = None
    search_spin_left: float = 0.0
    map_state: int = 0
    map_buf: bytearray = field(default_factory=bytearray)
    map_total: int = 0
    map_loaded: bool = False
    pose_set_at: float | None = None
    map_seq: int = 0
    t0: float = 0.0
    rx_count: int = 0
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        if self.with_map:
            self.map_loaded = True
            self.map_state = 2
            self.pose_set_at = -10.0

    # ---------------------------------------------------------------- 报文
    def handle(self, msg: bytes, now: float) -> list[bytes]:
        """处理一条主机报文，返回需要立即回发的报文（MAP_ACK）"""
        m = nv.decode_host(msg)
        if m is None:
            return []
        self.rx_count += 1
        f = m.fields
        if m.type == nv.GOAL:
            self._set_goal(f["x"] / 1000, f["y"] / 1000)
        elif m.type == nv.WAYPOINTS:
            self.wps = [(x / 1000, y / 1000) for x, y in f["points"]]
            self.wp_i, self.wp_loop = 0, f["loop"]
            self.goal = self.wps[0]
            self._set_mode(1)
        elif m.type == nv.SET_POSE:
            self.x, self.y = f["x"] / 1000, f["y"] / 1000
            self.yaw = math.radians(f["yaw_cdeg"] / 100)
            self.pose_set_at = now
        elif m.type == nv.TARGET:
            if f["found"]:
                cap = now - f["latency_ms"] / 1000
                if cap >= self.target_t:
                    bx, by = f["x"] / 1000, f["y"] / 1000
                    c, s = math.cos(self.yaw), math.sin(self.yaw)
                    self.target = (self.x + c * bx - s * by, self.y + s * bx + c * by)
                    self.target_t = cap
                    self.target_id = f["track_id"]
                if self.mode == 3:
                    self._set_mode(2)
        elif m.type == nv.MODE:
            if f["mode"] <= 4:
                self._set_mode(f["mode"])
        elif m.type == nv.MAP_BEGIN:
            self.map_total, self.map_buf, self.map_state = f["total"], bytearray(), 1
            return [nv.encode_map_ack(0, self.map_state)]
        elif m.type == nv.MAP_DATA:
            if self.map_state == 1 and f["offset"] == len(self.map_buf):
                self.map_buf += f["data"]
            return [nv.encode_map_ack(len(self.map_buf), self.map_state)]
        elif m.type == nv.MAP_END:
            try:
                if len(self.map_buf) != self.map_total:
                    raise MapPackageError("长度不符")
                parse_package(bytes(self.map_buf))
                self.map_state, self.map_loaded, self.pose_set_at = 2, True, None
                self.map_seq += 1
            except MapPackageError as exc:
                self.map_state = 3 if "CRC" in str(exc) or "长度" in str(exc) else 4
                self.map_loaded = False
            return [nv.encode_map_ack(len(self.map_buf), self.map_state)]
        elif m.type == nv.MAP_CLEAR:
            self.map_state, self.map_loaded, self.pose_set_at = 0, False, None
            return [nv.encode_map_ack(0, 0)]
        return []

    def _set_goal(self, gx: float, gy: float) -> None:
        self.goal = (gx, gy)
        self.wps = []
        self._set_mode(1)

    def _set_mode(self, mode: int) -> None:
        self.mode = mode
        self.state = {0: 0, 1: 1, 2: 4, 3: 5, 4: 6}[mode]
        if mode == 3:
            self.search_goal = None
            self.search_spin_left = 2 * math.pi
        if mode in (0, 4):
            self.vx = self.wz = 0.0

    # ---------------------------------------------------------------- 仿真
    def loc_state(self, now: float) -> tuple[int, int]:
        if not self.map_loaded:
            return 0, 0
        if self.pose_set_at is None:
            return 4, 0
        if now - self.pose_set_at < 1.6:
            return 1, 30
        return 2, 90

    def localized(self, now: float) -> bool:
        return not self.map_loaded or self.loc_state(now)[0] == 2

    def step(self, dt: float, now: float) -> None:
        vx = wz = 0.0
        if self.mode in (1, 2, 3) and not self.localized(now):
            vx = wz = 0.0                         # 有图未对准：原地保持
        elif self.mode == 1:
            last = not self.wps or (self.wp_i + 1 >= len(self.wps) and not self.wp_loop)
            arrived, vx, wz = self._drive(self.goal, GOAL_TOL_M if last else WP_TOL_M)
            if arrived:
                if last:
                    self.mode, self.state = 0, 2
                    vx = wz = 0.0
                else:
                    self.wp_i = (self.wp_i + 1) % len(self.wps)
                    self.goal = self.wps[self.wp_i]
            else:
                self.state = 1
        elif self.mode == 2:
            if self.target is None or now - self.target_t > TARGET_TIMEOUT_S:
                self._set_mode(3)
            else:
                tx, ty = self.target
                d = math.hypot(tx - self.x, ty - self.y)
                if d <= STANDOFF_M:
                    gx, gy = self.x, self.y
                else:
                    gx = tx - (tx - self.x) * STANDOFF_M / d
                    gy = ty - (ty - self.y) * STANDOFF_M / d
                self.goal = (gx, gy)
                arrived, vx, wz = self._drive(self.goal, TRACK_HOLD_M)
                if arrived:
                    vx = 0.0
                    dh = _wrap(math.atan2(ty - self.y, tx - self.x) - self.yaw)
                    wz = 0.0 if abs(dh) < math.radians(5) else max(-W_MAX / 2, min(W_MAX / 2, dh * 1.2))
                self.state = 4
        elif self.mode == 3:
            if self.target is not None and now - self.target_t <= TARGET_TIMEOUT_S:
                self._set_mode(2)
            elif self.search_spin_left > 0:
                wz = 0.8
                self.search_spin_left -= wz * dt
            else:
                if self.search_goal is None:
                    self.search_goal = self._pick_search_goal()
                self.goal = self.search_goal
                arrived, vx, wz = self._drive(self.search_goal, 0.25)
                if arrived:
                    self.search_goal = None
                    self.search_spin_left = 2 * math.pi
            if self.mode == 3:
                self.state = 5
        self.vx, self.wz = vx, wz
        self.yaw = _wrap(self.yaw + wz * dt)
        self.x += vx * math.cos(self.yaw) * dt
        self.y += vx * math.sin(self.yaw) * dt

    def _drive(self, goal: tuple[float, float], tol: float) -> tuple[bool, float, float]:
        dx, dy = goal[0] - self.x, goal[1] - self.y
        d = math.hypot(dx, dy)
        if d < tol:
            return True, 0.0, 0.0
        e = _wrap(math.atan2(dy, dx) - self.yaw)
        wz = max(-W_MAX, min(W_MAX, 1.8 * e))
        vx = 0.0 if abs(e) > 0.6 else min(V_MAX, 0.9 * d) * math.cos(e)
        return False, vx, wz

    def _pick_search_goal(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bounds
        for _ in range(50):
            gx, gy = self.rng.uniform(x0 + 0.4, x1 - 0.4), self.rng.uniform(y0 + 0.4, y1 - 0.4)
            if math.hypot(gx - self.x, gy - self.y) > 1.2:
                return gx, gy
        return (x0 + x1) / 2, (y0 + y1) / 2

    def status(self, now: float) -> nv.NavStatus:
        loc, q = self.loc_state(now)
        valid = self.target is not None and now - self.target_t <= TARGET_TIMEOUT_S
        flags = (nv.FLAG_TARGET_VALID if valid else 0) | nv.FLAG_LIDAR_OK | nv.FLAG_ODOM_OK
        return nv.NavStatus(
            mode=self.mode, state=self.state, map_seq=self.map_seq,
            x_mm=nv.m_to_mm(self.x), y_mm=nv.m_to_mm(self.y), yaw_cdeg=nv.rad_to_cdeg(self.yaw),
            goal_x_mm=nv.m_to_mm(self.goal[0]), goal_y_mm=nv.m_to_mm(self.goal[1]),
            vx_mmps=int(self.vx * 1000), wz_mradps=int(self.wz * 1000), flags=flags,
            t_us=int((now - self.t0) * 1e6) & 0xFFFFFFFF, loc_state=loc, loc_quality=q,
        )

    # ---------------------------------------------------------------- 虚拟相机 / 底盘遥测
    def observe(self, world: list[WorldObject], now: float, hfov_deg: float = 60.0,
                max_range: float = 4.0, noise_m: float = 0.02) -> list[dict]:
        out = []
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        for i, obj in enumerate(world):
            ox, oy = obj.position(now)
            dx, dy = ox - self.x, oy - self.y
            bx, by = c * dx + s * dy, -s * dx + c * dy
            dist = math.hypot(bx, by)
            if bx <= 0.3 or dist > max_range or abs(math.degrees(math.atan2(by, bx))) > hfov_deg / 2:
                continue
            if self.rng.random() > 0.95:
                continue
            out.append({
                "cls": obj.cls, "color": obj.color, "conf": round(0.8 + 0.15 * self.rng.random(), 3),
                "track_id": i + 1,
                "x": round(bx + self.rng.gauss(0, noise_m), 3), "y": round(by + self.rng.gauss(0, noise_m), 3),
                "z": round(obj.z, 3), "bbox": [0, 0, 0, 0],
            })
        return out

    def telemetry_frame(self, seq: int, now: float) -> bytes:
        left = self.vx - self.wz * TRACK_WIDTH_M / 2
        right = self.vx + self.wz * TRACK_WIDTH_M / 2
        pitch = math.radians(1.5 * math.sin(now * 0.7))
        return tm.encode_frame({
            "timestamp_ms": int((now - self.t0) * 1000) & 0xFFFFFFFF, "sequence": seq & 0xFFFF,
            "status": tm.ST_BMI_READY | (0 if self.mode == 4 else tm.ST_ACTIVE),
            "az_raw": -10920, "wz_q12": int(self.wz * 4096),
            "gravity_x_q12": int(math.sin(pitch) * 4096), "gravity_z_q12": int(-math.cos(pitch) * 4096),
            "forward_q12": int(self.vx / V_MAX * 4096), "yaw_q12": int(self.wz / W_MAX * 4096),
            "height_q12": int(0.16 * 4096),
            "left_target_mmps": int(left * 1000), "right_target_mmps": int(right * 1000),
            "left_cms": int(left * 100), "right_cms": int(right * 100),
            "lh_us": 1500, "lk_us": 1500, "rh_us": 1500, "rk_us": 1500,
        })


def _addr(spec: str, default_port: int) -> tuple[str, int]:
    host, _, port = spec.rpartition(":") if ":" in spec else (spec, "", "")
    return (host or "127.0.0.1", int(port) if port else default_port)


def serve(args: argparse.Namespace) -> None:
    core = MockFpgaCore(with_map=args.with_map, seed=args.seed)
    world = default_world()
    core.t0 = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(_addr(args.listen, 9000))
    sock.settimeout(0.01)
    peer = _addr(args.peer, 9001) if args.peer else None
    cam = _addr(args.camera_udp, 9102) if args.camera_udp else None
    tel = _addr(args.telemetry_udp, 9104) if args.telemetry_udp else None
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"mock_fpga: 监听 {args.listen}，相机 {cam}，遥测 {tel}，有图={args.with_map}", flush=True)

    last = time.monotonic()
    next_status = next_cam = next_tel = last
    tel_seq = cam_seq = 0
    while True:
        now = time.monotonic()
        try:
            data, src = sock.recvfrom(2048)
            if not args.peer:
                peer = src
            replies = core.handle(data, now)
            for r in replies:
                sock.sendto(r, peer)
        except (socket.timeout, BlockingIOError, ConnectionResetError):
            pass
        now = time.monotonic()
        while now - last >= 0.02:
            core.step(0.02, last + 0.02)
            last += 0.02
        if now >= next_status:
            next_status = max(next_status + 0.2, now - 0.1)
            if peer:
                sock.sendto(nv.encode_status(core.status(now)), peer)
        if cam and now >= next_cam:
            next_cam = max(next_cam + 0.1, now - 0.05)
            cam_seq += 1
            objs = core.observe(world, now)
            msg = {"type": "detections", "source": "mock_camera", "frame_seq": cam_seq,
                   "stamp_mono": now - 0.06, "stamp_wall": time.time() - 0.06, "objects": objs}
            out.sendto(json.dumps(msg).encode(), cam)
        if tel and now >= next_tel:
            next_tel = max(next_tel + 0.02, now - 0.01)
            tel_seq += 1
            out.sendto(core.telemetry_frame(tel_seq, now), tel)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", default="127.0.0.1:9000")
    ap.add_argument("--peer", default=None, help="固定回发地址（缺省：最近一次收到合法报文的源地址）")
    ap.add_argument("--camera-udp", default=None, help="虚拟相机检测结果发往 fpga_bridge 的感知端口")
    ap.add_argument("--telemetry-udp", default=None, help="底盘控制 V2 遥测发往 fpga_bridge 的端口")
    ap.add_argument("--with-map", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    try:
        serve(ap.parse_args())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
