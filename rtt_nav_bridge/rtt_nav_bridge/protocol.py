from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Union


@dataclass(frozen=True)
class OdomFrame:
    timestamp_ms: int
    x: float | None
    y: float | None
    yaw: float | None
    vx: float
    vy: float
    wz: float
    pose_valid: bool


@dataclass(frozen=True)
class ImuFrame:
    timestamp_ms: int
    qw: float
    qx: float
    qy: float
    qz: float
    gx: float
    gy: float
    gz: float
    ax: float
    ay: float
    az: float


@dataclass(frozen=True)
class StatFrame:
    timestamp_ms: int
    mode: str
    battery_mv: int
    estop: bool
    fault_code: int


ParsedFrame = Union[OdomFrame, ImuFrame, StatFrame]


class ProtocolError(ValueError):
    pass


def parse_nav_line(line: str) -> ParsedFrame:
    stripped = line.strip()
    if not stripped:
        raise ProtocolError('empty frame')
    parts = [item.strip() for item in stripped.split(',')]
    frame_type = parts[0].upper()
    if frame_type == 'ODOM':
        return _parse_odom(parts)
    if frame_type == 'IMU':
        return _parse_imu(parts)
    if frame_type == 'STAT':
        return _parse_stat(parts)
    raise ProtocolError(f'unknown frame type: {parts[0]}')


def format_cmd(timestamp_ms: int, vx: float, vy: float, wz: float) -> str:
    return f'CMD,{timestamp_ms},{vx:.6f},{vy:.6f},{wz:.6f}\n'


def format_heartbeat(timestamp_ms: int) -> str:
    return f'HB,{timestamp_ms}\n'


def format_stop(timestamp_ms: int, reason: str) -> str:
    safe_reason = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in reason) or 'unknown'
    return f'STOP,{timestamp_ms},{safe_reason}\n'


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return _normalize_quaternion(qw, qx, qy, qz)


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    return euler_to_quaternion(0.0, 0.0, yaw)


def _parse_odom(parts: list[str]) -> OdomFrame:
    if len(parts) == 8:
        return OdomFrame(
            timestamp_ms=_int(parts[1]),
            x=_float(parts[2]),
            y=_float(parts[3]),
            yaw=_float(parts[4]),
            vx=_float(parts[5]),
            vy=_float(parts[6]),
            wz=_float(parts[7]),
            pose_valid=True,
        )
    if len(parts) == 5:
        return OdomFrame(
            timestamp_ms=_int(parts[1]),
            x=None,
            y=None,
            yaw=None,
            vx=_float(parts[2]),
            vy=_float(parts[3]),
            wz=_float(parts[4]),
            pose_valid=False,
        )
    raise ProtocolError(f'ODOM expects 5 or 8 fields, got {len(parts)}')


def _parse_imu(parts: list[str]) -> ImuFrame:
    if len(parts) == 12:
        qw, qx, qy, qz = _normalize_quaternion(_float(parts[2]), _float(parts[3]), _float(parts[4]), _float(parts[5]))
        offset = 6
    elif len(parts) == 11:
        qw, qx, qy, qz = euler_to_quaternion(_float(parts[2]), _float(parts[3]), _float(parts[4]))
        offset = 5
    else:
        raise ProtocolError(f'IMU expects 11 Euler fields or 12 quaternion fields, got {len(parts)}')
    return ImuFrame(
        timestamp_ms=_int(parts[1]),
        qw=qw,
        qx=qx,
        qy=qy,
        qz=qz,
        gx=_float(parts[offset]),
        gy=_float(parts[offset + 1]),
        gz=_float(parts[offset + 2]),
        ax=_float(parts[offset + 3]),
        ay=_float(parts[offset + 4]),
        az=_float(parts[offset + 5]),
    )


def _parse_stat(parts: list[str]) -> StatFrame:
    if len(parts) != 6:
        raise ProtocolError(f'STAT expects 6 fields, got {len(parts)}')
    return StatFrame(
        timestamp_ms=_int(parts[1]),
        mode=parts[2],
        battery_mv=_int(parts[3]),
        estop=bool(_int(parts[4])),
        fault_code=_int(parts[5]),
    )


def _normalize_quaternion(qw: float, qx: float, qy: float, qz: float) -> tuple[float, float, float, float]:
    norm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    if norm <= 1e-9:
        raise ProtocolError('zero quaternion')
    return qw / norm, qx / norm, qy / norm, qz / norm


def _float(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ProtocolError(f'invalid float: {value}') from exc


def _int(value: str) -> int:
    try:
        return int(value, 10)
    except ValueError as exc:
        raise ProtocolError(f'invalid int: {value}') from exc
