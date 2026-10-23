"""导航主机报文（NV 协议 v1）编解码。

与导航仓库 fw/nav/proto.h、docs/2_interface/icd.md、tools/nav_host.py 一一对应：
公共头 4 字节 'N' 'V' | 版本=1 | 类型，负载小端。坐标单位 mm，角度单位 0.01°（cdeg）。

RK3588 只发任务级报文（GOAL / WAYPOINTS / SET_POSE / TARGET / MODE / MAP_*），
不发速度：速度由 FPGA 导航经 SAFE 限幅后交给 FPGA 控制（分层架构的硬约束）。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Iterable, Sequence
from yuntuo.fpga_link.telemetry import ControlFrame, decode_packet

MAGIC = b"NV"
VERSION = 1

GOAL = 0x10
WAYPOINTS = 0x11
SET_POSE = 0x12
TARGET = 0x20
MODE = 0x30
MAP_BEGIN = 0x40
MAP_DATA = 0x41
MAP_END = 0x42
MAP_CLEAR = 0x43
STATUS = 0x80
PATH = 0x81
MAP_ACK = 0x82
CONTROL_V2 = 0x83  # exactly the original A5 5A / V2 / 120-byte payload / CRC16 frame

YAW_DONT_CARE = 0x7FFFFFFF
MAX_WAYPOINTS = 32
MAP_CHUNK = 1024

MODES = {"idle": 0, "goto": 1, "track": 2, "search": 3, "estop": 4}
MODE_NAMES = {v: k for k, v in MODES.items()}
STATE_NAMES = {0: "idle", 1: "moving", 2: "arrived", 3: "blocked", 4: "tracking", 5: "searching", 6: "estop"}
STATE_LABELS = {0: "空闲", 1: "行进", 2: "到达", 3: "受阻", 4: "跟踪", 5: "探索", 6: "急停"}
LOC_NAMES = {0: "mapless", 1: "aligning", 2: "ok", 3: "degraded", 4: "lost"}
LOC_LABELS = {0: "无图", 1: "对准中", 2: "正常", 3: "退化", 4: "丢失"}
MAP_STATE_NAMES = {0: "none", 1: "receiving", 2: "loaded", 3: "crc_error", 4: "format_error"}

# STATUS.flags（fw/nav/proto.h STF_*）
FLAG_TARGET_VALID = 0x0001
FLAG_MAP_STALE = 0x0002
FLAG_LIDAR_OK = 0x0004   # 固件里取 have_map：雷达局部图在更新
FLAG_ODOM_OK = 0x0008

_STATUS_BODY = struct.Struct("<BBHiiiiihhHHI")   # 36 B
_TARGET_BODY = struct.Struct("<BBHiiiHH")        # 20 B
_SET_POSE_BODY = struct.Struct("<iiiHHHH")       # 20 B

_INT32_MIN, _INT32_MAX = -(1 << 31), (1 << 31) - 1


class ProtocolError(ValueError):
    pass


def header(msg_type: int) -> bytes:
    return MAGIC + bytes((VERSION, msg_type))


def _i32(value: int, name: str) -> int:
    value = int(value)
    if not _INT32_MIN <= value <= _INT32_MAX:
        raise ProtocolError(f"{name} 超出 int32 范围：{value}")
    return value


def _clamp(value: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(value))))


# ---------------------------------------------------------------- 主机 -> FPGA
def encode_goal(x_mm: int, y_mm: int, yaw_cdeg: int = YAW_DONT_CARE) -> bytes:
    return header(GOAL) + struct.pack("<iii", _i32(x_mm, "x_mm"), _i32(y_mm, "y_mm"), _i32(yaw_cdeg, "yaw_cdeg"))


def encode_waypoints(points: Sequence[tuple[int, int]], loop: bool = False) -> bytes:
    if not 1 <= len(points) <= MAX_WAYPOINTS:
        raise ProtocolError(f"路径点数量须在 1..{MAX_WAYPOINTS}，当前 {len(points)}")
    body = struct.pack("<BBH", len(points), 1 if loop else 0, 0)
    body += b"".join(struct.pack("<ii", _i32(x, "x_mm"), _i32(y, "y_mm")) for x, y in points)
    return header(WAYPOINTS) + body


def encode_set_pose(x_mm: int, y_mm: int, yaw_cdeg: int, align: bool = True,
                    range_mm: int = 0, range_cdeg: int = 0) -> bytes:
    """有图：地图系初始位姿，align=True 时在先验图上搜索 ±range 对准（0 = 固件缺省 ±500 mm / ±10°）；
    无图：重置里程计原点。"""
    return header(SET_POSE) + _SET_POSE_BODY.pack(
        _i32(x_mm, "x_mm"), _i32(y_mm, "y_mm"), _i32(yaw_cdeg, "yaw_cdeg"), 1 if align else 0,
        _clamp(range_mm, 0, 0xFFFF), _clamp(range_cdeg, 0, 0xFFFF), 0)


def encode_target(x_mm: int, y_mm: int, z_mm: int = 0, *, found: bool = True, cls: int = 0,
                  conf_permille: int = 1000, latency_ms: int = 0, track_id: int = 0) -> bytes:
    """视觉目标（机身系 mm：x 前、y 左、z 上）。latency_ms = 采图到发出报文的时间，FPGA 据此查历史位姿。"""
    return header(TARGET) + _TARGET_BODY.pack(
        1 if found else 0, int(cls) & 0xFF, _clamp(conf_permille, 0, 1000),
        _i32(x_mm, "x_mm"), _i32(y_mm, "y_mm"), _i32(z_mm, "z_mm"),
        _clamp(latency_ms, 0, 0xFFFF), int(track_id) & 0xFFFF)


def encode_mode(mode: int | str) -> bytes:
    value = MODES[mode] if isinstance(mode, str) else int(mode)
    if value not in MODE_NAMES:
        raise ProtocolError(f"未知模式：{mode}")
    return header(MODE) + bytes((value, 0, 0, 0))


def encode_map_begin(total_len: int) -> bytes:
    return header(MAP_BEGIN) + struct.pack("<I", int(total_len))


def encode_map_data(offset: int, chunk: bytes) -> bytes:
    if len(chunk) > MAP_CHUNK:
        raise ProtocolError(f"MAP_DATA 单块最多 {MAP_CHUNK} 字节")
    return header(MAP_DATA) + struct.pack("<I", int(offset)) + bytes(chunk)


def encode_map_end() -> bytes:
    return header(MAP_END)


def encode_map_clear() -> bytes:
    return header(MAP_CLEAR)


def map_messages(package: bytes) -> list[bytes]:
    """先验地图包 -> BEGIN、按 1 KB 分块的 DATA、END"""
    msgs = [encode_map_begin(len(package))]
    msgs += [encode_map_data(off, package[off:off + MAP_CHUNK]) for off in range(0, len(package), MAP_CHUNK)]
    msgs.append(encode_map_end())
    return msgs


# ---------------------------------------------------------------- FPGA -> 主机
@dataclass(frozen=True)
class NavStatus:
    mode: int
    state: int
    map_seq: int
    x_mm: int
    y_mm: int
    yaw_cdeg: int
    goal_x_mm: int
    goal_y_mm: int
    vx_mmps: int
    wz_mradps: int
    flags: int
    t_us: int
    loc_state: int | None = None
    loc_quality: int | None = None

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.mode, f"mode{self.mode}")

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, f"state{self.state}")

    @property
    def loc_name(self) -> str | None:
        if self.loc_state is None:
            return None
        return LOC_NAMES.get(self.loc_state, f"loc{self.loc_state}")

    @property
    def target_valid(self) -> bool:
        return bool(self.flags & FLAG_TARGET_VALID)

    @property
    def map_stale(self) -> bool:
        return bool(self.flags & FLAG_MAP_STALE)

    @property
    def lidar_ok(self) -> bool:
        return bool(self.flags & FLAG_LIDAR_OK)

    @property
    def odom_ok(self) -> bool:
        return bool(self.flags & FLAG_ODOM_OK)

    @property
    def yaw_rad(self) -> float:
        return math.radians(self.yaw_cdeg / 100.0)

    def distance_to_goal_mm(self) -> float:
        return math.hypot(self.goal_x_mm - self.x_mm, self.goal_y_mm - self.y_mm)


@dataclass(frozen=True)
class MapAck:
    next_offset: int
    map_state: int

    @property
    def map_state_name(self) -> str:
        return MAP_STATE_NAMES.get(self.map_state, f"map{self.map_state}")


@dataclass(frozen=True)
class NavPath:
    points: tuple[tuple[int, int], ...]


def decode(b: bytes | None) -> NavStatus | MapAck | NavPath | ControlFrame | None:
    """FPGA -> 主机报文；不认识或长度不足返回 None"""
    if not b or len(b) < 4 or b[:2] != MAGIC or b[2] != VERSION:
        return None
    t = b[3]
    if t == CONTROL_V2:
        return decode_packet(b[4:]) if len(b) == 130 and b[4:8] == b"\xa5\x5a\x02\x78" else None
    if t == STATUS and len(b) >= 4 + _STATUS_BODY.size:
        fields = _STATUS_BODY.unpack_from(b, 4)
        loc_state = b[40] if len(b) >= 42 else None
        loc_quality = b[41] if len(b) >= 42 else None
        m, st, seq, x, y, yaw, gx, gy, vx, wz, flags, _rsv, t_us = fields
        return NavStatus(m, st, seq, x, y, yaw, gx, gy, vx, wz, flags, t_us, loc_state, loc_quality)
    if t == MAP_ACK and len(b) >= 9:
        nxt, st = struct.unpack_from("<IB", b, 4)
        return MapAck(nxt, st)
    if t == PATH and len(b) >= 8:
        n = b[4]
        pts = tuple(struct.unpack_from("<ii", b, 8 + 8 * i) for i in range(n) if len(b) >= 16 + 8 * i)
        return NavPath(pts)
    return None


# ---------------------------------------------------------------- 模拟器 / 测试用：反方向编解码
def encode_status(s: NavStatus) -> bytes:
    body = _STATUS_BODY.pack(s.mode, s.state, s.map_seq & 0xFFFF, s.x_mm, s.y_mm, s.yaw_cdeg, s.goal_x_mm,
                             s.goal_y_mm, _clamp(s.vx_mmps, -32768, 32767), _clamp(s.wz_mradps, -32768, 32767),
                             s.flags & 0xFFFF, 0, s.t_us & 0xFFFFFFFF)
    tail = bytes((s.loc_state or 0, s.loc_quality or 0, 0, 0))
    return header(STATUS) + body + tail


def encode_map_ack(next_offset: int, map_state: int) -> bytes:
    return header(MAP_ACK) + struct.pack("<IB3x", next_offset, map_state)


@dataclass
class HostMessage:
    type: int
    fields: dict = field(default_factory=dict)


def decode_host(b: bytes) -> HostMessage | None:
    """主机 -> FPGA 报文（模拟器用）"""
    if len(b) < 4 or b[:2] != MAGIC or b[2] != VERSION:
        return None
    t = b[3]
    p = b[4:]
    try:
        if t == GOAL:
            x, y, yaw = struct.unpack_from("<iii", p)
            return HostMessage(t, {"x": x, "y": y, "yaw_cdeg": yaw})
        if t == WAYPOINTS:
            n, loop, _ = struct.unpack_from("<BBH", p)
            if n == 0 or n > MAX_WAYPOINTS:
                return None
            pts = [struct.unpack_from("<ii", p, 4 + 8 * i) for i in range(n)]
            return HostMessage(t, {"points": pts, "loop": bool(loop)})
        if t == SET_POSE:
            x, y, yaw, flags, rmm, rcd, _ = _SET_POSE_BODY.unpack_from(p)
            return HostMessage(t, {"x": x, "y": y, "yaw_cdeg": yaw, "align": bool(flags & 1),
                                   "range_mm": rmm, "range_cdeg": rcd})
        if t == TARGET:
            found, cls, conf, x, y, z, lat, tid = _TARGET_BODY.unpack_from(p)
            return HostMessage(t, {"found": bool(found), "cls": cls, "conf": conf, "x": x, "y": y, "z": z,
                                   "latency_ms": lat, "track_id": tid})
        if t == MODE:
            return HostMessage(t, {"mode": p[0]})
        if t == MAP_BEGIN:
            return HostMessage(t, {"total": struct.unpack_from("<I", p)[0]})
        if t == MAP_DATA:
            return HostMessage(t, {"offset": struct.unpack_from("<I", p)[0], "data": bytes(p[4:])})
        if t in (MAP_END, MAP_CLEAR):
            return HostMessage(t, {})
    except (struct.error, IndexError):
        return None
    return None


def m_to_mm(value_m: float) -> int:
    return int(round(value_m * 1000.0))


def rad_to_cdeg(value_rad: float) -> int:
    deg = math.degrees(value_rad)
    deg = (deg + 180.0) % 360.0 - 180.0
    return int(round(deg * 100.0))


def iter_messages(msgs: Iterable[bytes]) -> Iterable[HostMessage]:
    for m in msgs:
        decoded = decode_host(m)
        if decoded is not None:
            yield decoded
