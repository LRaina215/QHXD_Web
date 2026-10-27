"""底盘控制遥测（控制仓库 Chenyudog/fpga，tools/fpga_telemetry，V1/V2 兼容）解码。

帧：A5 5A | 版本 | 负载长度 | 负载（小端）| CRC16-CCITT-FALSE（覆盖版本、长度、负载，低字节先发）。
  V1：版本 1、长度 100，50 Hz；V2：版本 2、长度 120（追加 PID 诊断），100 Hz。230400 8N1，FPGA TX = P11-40。
控制坐标系：X 右、Y 前、Z 上（导航坐标系是 X 前、Y 左、Z 上）。

只读：RK3588 不经这条线给底盘发速度（自主模式下速度只能来自 FPGA 导航）。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

MAGIC = b"\xa5\x5a"
_V1 = struct.Struct("<IH6B6h6i3i2i2h2h4HII2i")
_V2 = struct.Struct(_V1.format + "4i2H")
assert _V1.size == 100 and _V2.size == 120

NAMES_V1 = (
    "timestamp_ms sequence status policy_fault sensor_error left_fault right_fault fusion_flags "
    "ax_raw ay_raw az_raw gx_raw gy_raw gz_raw "
    "wx_q12 wy_q12 wz_q12 gravity_x_q12 gravity_y_q12 gravity_z_q12 "
    "forward_q12 yaw_q12 height_q12 left_target_mmps right_target_mmps "
    "left_cms right_cms left_duty right_duty lh_us lk_us rh_us rk_us "
    "completed_frames inference_cycles left_delta right_delta"
).split()
NAMES_V2_EXTRA = (
    "left_reference_mmps right_reference_mmps left_error_mmps right_error_mmps "
    "left_control_sequence right_control_sequence"
).split()
FORMATS = {(1, 100): (_V1, NAMES_V1), (2, 120): (_V2, NAMES_V1 + NAMES_V2_EXTRA)}

# status 位（控制仓库 fpga/src/mem_policy.v status_flags）
ST_BMI_READY = 1 << 0
ST_CALIBRATING = 1 << 1
ST_BIAS_SUSPECT = 1 << 2
ST_SAMPLE_STALE = 1 << 3
ST_POLICY_FAULT = 1 << 4
ST_ACTUATOR_FAULT = 1 << 5
ST_STOP_LATCHED = 1 << 6
ST_ACTIVE = 1 << 7

ACCEL_LSB_PER_G = 10920.0
Q12 = 4096.0


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class ControlFrame:
    version: int
    raw: dict

    @property
    def sequence(self) -> int:
        return self.raw["sequence"]

    @property
    def timestamp_s(self) -> float:
        return self.raw["timestamp_ms"] / 1000.0

    @property
    def status(self) -> int:
        return self.raw["status"]

    @property
    def active(self) -> bool:
        return bool(self.status & ST_ACTIVE)

    @property
    def stop_latched(self) -> bool:
        return bool(self.status & ST_STOP_LATCHED)

    @property
    def calibrated(self) -> bool:
        return not (self.raw["fusion_flags"] & 3) and bool(self.status & ST_BMI_READY)

    @property
    def roll_deg(self) -> float | None:
        if not self.calibrated:
            return None
        gx, gz = self.raw["gravity_x_q12"] / Q12, self.raw["gravity_z_q12"] / Q12
        return math.degrees(math.atan2(gx, -gz))

    @property
    def pitch_deg(self) -> float | None:
        if not self.calibrated:
            return None
        gx, gy, gz = (self.raw[f"gravity_{a}_q12"] / Q12 for a in "xyz")
        return math.degrees(math.atan2(gy, math.hypot(gx, gz)))

    @property
    def yaw_rate_radps(self) -> float:
        return self.raw["wz_q12"] / Q12

    @property
    def wheel_left_mps(self) -> float:
        return self.raw["left_cms"] / 100.0

    @property
    def wheel_right_mps(self) -> float:
        return self.raw["right_cms"] / 100.0

    @property
    def forward_cmd(self) -> float:
        return self.raw["forward_q12"] / Q12

    @property
    def yaw_cmd(self) -> float:
        return self.raw["yaw_q12"] / Q12

    @property
    def height_cmd(self) -> float:
        return self.raw["height_q12"] / Q12

    def faults(self) -> list[str]:
        out = []
        st = self.status
        if st & ST_POLICY_FAULT or self.raw["policy_fault"]:
            out.append(f"policy_fault:{self.raw['policy_fault']}")
        if self.raw["sensor_error"]:
            out.append(f"bmi088_error:{self.raw['sensor_error']}")
        if st & ST_SAMPLE_STALE:
            out.append("bmi088_stale")
        if st & ST_ACTUATOR_FAULT:
            out.append("actuator_fault")
        if self.raw["left_fault"]:
            out.append(f"left_motor_fault:{self.raw['left_fault']}")
        if self.raw["right_fault"]:
            out.append(f"right_motor_fault:{self.raw['right_fault']}")
        return out


def decode_packet(packet: bytes) -> ControlFrame | None:
    """Validate exactly one datagram frame; never join fragments across UDP packets."""
    if len(packet) < 6 or packet[:2] != MAGIC:
        return None
    key = (packet[2], packet[3])
    if key not in FORMATS or len(packet) != key[1] + 6:
        return None
    if crc16_ccitt_false(packet[2:-2]) != int.from_bytes(packet[-2:], "little"):
        return None
    fmt, names = FORMATS[key]
    return ControlFrame(key[0], dict(zip(names, fmt.unpack(packet[4:-2]))))


class TelemetryDecoder:
    """字节流 -> ControlFrame 列表；坏 CRC 逐字节重同步。"""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.bad_crc = 0
        self.skipped = 0
        self.frames = 0
        self.last_sequence: int | None = None

    def feed(self, data: bytes) -> list[ControlFrame]:
        self.buffer.extend(data)
        out: list[ControlFrame] = []
        while len(self.buffer) >= 4:
            idx = self.buffer.find(MAGIC)
            if idx < 0:
                del self.buffer[:-1]
                break
            if idx:
                del self.buffer[:idx]
            if len(self.buffer) < 4:
                break
            key = (self.buffer[2], self.buffer[3])
            if key not in FORMATS:
                del self.buffer[0]
                continue
            length = key[1]
            size = length + 6
            if len(self.buffer) < size:
                break
            packet = bytes(self.buffer[:size])
            if crc16_ccitt_false(packet[2:length + 4]) != int.from_bytes(packet[length + 4:size], "little"):
                self.bad_crc += 1
                del self.buffer[0]
                continue
            del self.buffer[:size]
            fmt, names = FORMATS[key]
            raw = dict(zip(names, fmt.unpack(packet[4:length + 4])))
            if self.last_sequence is not None:
                delta = (raw["sequence"] - self.last_sequence) & 0xFFFF
                if 1 < delta < 32768:
                    self.skipped += delta - 1
            self.last_sequence = raw["sequence"]
            self.frames += 1
            out.append(ControlFrame(key[0], raw))
        if len(self.buffer) > 4096:
            del self.buffer[:-256]
        return out


def encode_frame(values: dict, version: int = 2) -> bytes:
    """模拟器 / 测试用：按字段名打包一帧（缺省字段填 0）"""
    fmt, names = FORMATS[(1, 100)] if version == 1 else FORMATS[(2, 120)]
    payload = fmt.pack(*(int(values.get(n, 0)) for n in names))
    body = bytes((version, fmt.size)) + payload
    return MAGIC + body + crc16_ccitt_false(body).to_bytes(2, "little")
