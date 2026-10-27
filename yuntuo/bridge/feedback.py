"""Conservative task-level stop evidence; never a physical standstill certificate.

The existing cm/s fields are coarse. Also veto nonzero encoder gate deltas,
require consecutive publications and healthy fusion, and retain that limitation.
No encoder snapshot is integrated as displacement here.
"""
from __future__ import annotations

from dataclasses import dataclass

from yuntuo.fpga_link import telemetry as tm

FEEDBACK_MAX_AGE_S = 0.050
STOP_HOLD_S = 0.500
STOP_V_MMPS = 5
STOP_W_MRADPS = 20


@dataclass(frozen=True)
class MotionView:
    ready: bool = False
    quiet_since: float | None = None
    stopped: bool = False
    reason: str = "缺少控制反馈"


class StopEvidence:
    def __init__(self) -> None:
        self.frame: tm.ControlFrame | None = None
        self.received_at = -1e9
        self.quiet_since: float | None = None
        self.quiet_stamp: int | None = None

    def reset(self) -> None:
        self.__init__()

    def ingest(self, frame: tm.ControlFrame, at: float, *, clock_ok: bool = True) -> bool:
        previous = self.frame
        consecutive = False
        if previous is not None:
            ds = (frame.sequence - previous.sequence) & 0xFFFF
            dt = (frame.raw["timestamp_ms"] - previous.raw["timestamp_ms"]) & 0xFFFFFFFF
            if ds == 0 or ds >= 0x8000 or dt == 0 or dt >= 0x80000000:
                return False  # no health refresh from repeated/reordered publications
            consecutive = ds == 1 and dt <= 50 and 0 <= at-self.received_at <= FEEDBACK_MAX_AGE_S
        self.frame, self.received_at = frame, at
        healthy = (frame.calibrated and not frame.faults() and not frame.stop_latched
                   and not frame.status & (tm.ST_CALIBRATING | tm.ST_BIAS_SUSPECT))
        quiet = (abs(frame.wheel_left_mps*1000) <= STOP_V_MMPS
                 and abs(frame.wheel_right_mps*1000) <= STOP_V_MMPS
                 and abs(frame.yaw_rate_radps*1000) <= STOP_W_MRADPS
                 and frame.raw["left_delta"] == 0 and frame.raw["right_delta"] == 0)
        if not (clock_ok and healthy and quiet):
            self.quiet_since = self.quiet_stamp = None
        elif not consecutive or self.quiet_since is None:
            self.quiet_since, self.quiet_stamp = at, frame.raw["timestamp_ms"]
        return True

    def view(self, now: float, *, clock_ok: bool = True) -> MotionView:
        f = self.frame
        if f is None:
            return MotionView()
        if not clock_ok or not 0 <= now-self.received_at <= FEEDBACK_MAX_AGE_S:
            return MotionView(reason="控制反馈过期或时钟未核对")
        if (not f.calibrated or f.faults() or f.stop_latched
                or f.status & (tm.ST_CALIBRATING | tm.ST_BIAS_SUSPECT)):
            return MotionView(reason="控制反馈故障或融合未就绪")
        if self.quiet_since is None:
            return MotionView(ready=True, reason="反馈仍有运动")
        device_span = ((f.raw["timestamp_ms"]-self.quiet_stamp) & 0xFFFFFFFF) / 1000
        stopped = now-self.quiet_since >= STOP_HOLD_S and device_span >= STOP_HOLD_S
        return MotionView(True, self.quiet_since, stopped, "反馈满足停稳条件" if stopped else "正在确认持续停稳")
