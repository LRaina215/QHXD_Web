"""fpga_bridge 的输入线程：感知检测（本机 UDP JSON）与底盘控制遥测（串口 / UDP）。"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from yuntuo.fpga_link.telemetry import ControlFrame, TelemetryDecoder

log = logging.getLogger("fpga_bridge")


class RateMeter:
    def __init__(self, window_s: float = 2.0) -> None:
        self.window_s = window_s
        self.stamps: deque[float] = deque()

    def mark(self, now: float) -> None:
        self.stamps.append(now)
        while self.stamps and now - self.stamps[0] > self.window_s:
            self.stamps.popleft()

    def rate(self, now: float) -> float:
        while self.stamps and now - self.stamps[0] > self.window_s:
            self.stamps.popleft()
        if len(self.stamps) < 2:
            return 0.0
        return (len(self.stamps) - 1) / max(1e-3, self.stamps[-1] - self.stamps[0])


@dataclass
class DetectionFrame:
    """感知节点 -> fpga_bridge 的一帧检测（机身系 m：x 前、y 左、z 上）"""
    seq: int
    stamp_mono: float | None
    stamp_wall: float | None
    received_mono: float
    objects: list[dict] = field(default_factory=list)
    source: str = "perception"

    def latency_ms(self, now_mono: float) -> float:
        if self.stamp_mono is not None and 0.0 <= now_mono - self.stamp_mono < 5.0:
            return (now_mono - self.stamp_mono) * 1000.0
        if self.stamp_wall is not None:
            lat = (time.time() - self.stamp_wall) * 1000.0
            if 0.0 <= lat < 5000.0:
                return lat
        return (now_mono - self.received_mono) * 1000.0


def parse_detection_message(data: bytes, received_mono: float, seq: int) -> DetectionFrame | None:
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(msg, dict) or msg.get("type") != "detections":
        return None
    objects = [o for o in msg.get("objects") or [] if isinstance(o, dict) and "cls" in o]
    return DetectionFrame(
        seq=int(msg.get("frame_seq") or seq), stamp_mono=msg.get("stamp_mono"), stamp_wall=msg.get("stamp_wall"),
        received_mono=received_mono, objects=objects, source=str(msg.get("source") or "perception"),
    )


class PerceptionInbox(threading.Thread):
    def __init__(self, addr: str) -> None:
        super().__init__(daemon=True, name="perception-inbox")
        host, _, port = addr.rpartition(":")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host or "127.0.0.1", int(port)))
        self.sock.settimeout(0.5)
        self.lock = threading.Lock()
        self._latest: DetectionFrame | None = None
        self._count = 0
        self.rate = RateMeter()

    def run(self) -> None:
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                return
            now = time.monotonic()
            self._count += 1
            frame = parse_detection_message(data, now, self._count)
            if frame is not None:
                with self.lock:
                    self._latest = frame
                    self.rate.mark(now)

    def latest(self) -> DetectionFrame | None:
        with self.lock:
            return self._latest


class TelemetryReader(threading.Thread):
    """serial:/dev/ttyUSB0[@230400] 或 udp:HOST:PORT（mock_fpga --telemetry-udp）"""

    def __init__(self, spec: str) -> None:
        super().__init__(daemon=True, name="control-telemetry")
        self.spec = spec
        self.decoder = TelemetryDecoder()
        self.lock = threading.Lock()
        self._latest: ControlFrame | None = None
        self._latest_at = 0.0
        self.rate = RateMeter()

    def latest(self) -> tuple[ControlFrame | None, float]:
        with self.lock:
            return self._latest, self._latest_at

    def _ingest(self, data: bytes) -> None:
        frames = self.decoder.feed(data)
        if frames:
            now = time.monotonic()
            with self.lock:
                self._latest, self._latest_at = frames[-1], now
                for _ in frames:
                    self.rate.mark(now)

    def run(self) -> None:
        kind, _, rest = self.spec.partition(":")
        if kind == "nv":
            return  # FpgaBridge receives CONTROL_V2 on its single navigation socket.
        while True:
            try:
                if kind == "udp":
                    host, _, port = rest.rpartition(":")
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.bind((host or "127.0.0.1", int(port)))
                    sock.settimeout(1.0)
                    while True:
                        try:
                            self._ingest(sock.recvfrom(4096)[0])
                        except socket.timeout:
                            continue
                else:
                    import serial

                    device, _, baud = rest.partition("@")
                    with serial.Serial(device, int(baud or 230400), timeout=0.2) as port:
                        while True:
                            self._ingest(port.read(512))
            except Exception as exc:  # 串口拔出、权限等：2 s 后重连
                log.warning("控制遥测 %s 不可用：%s", self.spec, exc)
                time.sleep(2.0)
