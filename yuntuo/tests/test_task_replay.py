"""Task/feedback regressions, production codec and state machine, no device I/O."""
import json

import pytest

from yuntuo.bridge.config import BridgeConfig
from yuntuo.bridge.core import FpgaBridge, PendingRequest
from yuntuo.bridge.feedback import StopEvidence
from yuntuo.bridge.inputs import DetectionFrame
from yuntuo.bridge.inputs import RateMeter
from yuntuo.bridge.poster import ListPoster
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link import telemetry as tm


class Replay:
    def __init__(self, tmp_path):
        wp, routes = tmp_path / "wp.json", tmp_path / "routes.json"
        wp.write_text(json.dumps([{"waypoint_id": "a", "pose": [2, 0, 0]}]), encoding="utf-8")
        routes.write_text("[]", encoding="utf-8")
        self.b = FpgaBridge(BridgeConfig(telemetry="nv", waypoints_path=wp, routes_path=routes),
                            link_factory=self.forbidden_link, poster=ListPoster())
        self.seq = 0

    @staticmethod
    def forbidden_link():
        raise AssertionError("Replay must never open a hardware/network link")

    def nav(self, now, **kw):
        fields = dict(mode=0, state=0, map_seq=1, x_mm=2000, y_mm=0, yaw_cdeg=0,
                      goal_x_mm=2000, goal_y_mm=0, vx_mmps=0, wz_mradps=0,
                      flags=nv.FLAG_ODOM_OK | nv.FLAG_LIDAR_OK, t_us=int(now*1e6) & 0xFFFFFFFF,
                      loc_state=0, loc_quality=80)
        fields.update(kw)
        self.b._on_message(nv.decode(nv.encode_status(nv.NavStatus(**fields))), now)

    def control(self, now, **kw):
        self.seq += 1
        values = dict(sequence=self.seq & 0xFFFF, timestamp_ms=round(now*1000) & 0xFFFFFFFF,
                      status=tm.ST_ACTIVE | tm.ST_BMI_READY, gravity_z_q12=-4096)
        values.update(kw)
        self.b._on_message(nv.decode(b"NV\x01\x83" + tm.encode_frame(values)), now)

    def command(self, command, now=100., **kw):
        return self.b._handle_request(PendingRequest("mission", {
            "command": command, "source": "replay", "payload": kw}), now)["data"]

    def start(self, kind="go_to_waypoint", **kw):
        self.nav(100.)
        assert self.command(kind, waypoint_id="a", target_class="bottle", **kw)["accepted"]
        self.nav(100.3, mode=1 if kind == "go_to_waypoint" else 3, state=1)
        self.b.runner.on_tick(self.b.status_view(100.3), None, 100.3)
        assert self.task.confirmed

    @property
    def task(self):
        return self.b.runner.task

    def run(self, start=100.4, seconds=1.4, *, control=None, nav=None, target=False):
        for i in range(round(seconds/.02)+1):
            now = round(start+i*.02, 6)
            opts = {"mode": 2, "state": 1, "flags": nv.FLAG_TARGET_VALID | nv.FLAG_ODOM_OK} if target else {"state": 2}
            opts.update(nav or {})
            self.nav(now, **opts)
            if control is not False:
                self.control(now, **(control or {}))
            frame = DetectionFrame(i, now, None, now, [{"cls": "bottle", "conf": .95, "x": .7,
                                                       "y": 0, "z": .1, "track_id": 1}]) if target else None
            self.b.runner.on_tick(self.b.status_view(now), frame, now)


@pytest.fixture
def replay(tmp_path):
    return Replay(tmp_path)


@pytest.mark.parametrize("control", [
    False, {"left_cms": 10, "right_cms": 10}, {"left_cms": 1}, {"wz_q12": 4096},
    {"status": tm.ST_BMI_READY | tm.ST_SAMPLE_STALE}, {"sensor_error": 1},
    {"policy_fault": 2}, {"left_fault": 1}, {"status": tm.ST_BMI_READY | tm.ST_CALIBRATING},
    {"status": tm.ST_BMI_READY | tm.ST_BIAS_SUSPECT}, {"fusion_flags": 1},
    {"status": tm.ST_ACTIVE}, {"left_delta": 1}, {"right_delta": -1},
])
def test_goto_rejects_bad_stop_evidence(replay, control):
    replay.start()
    replay.run(control=control)
    assert replay.task.state != "completed"
    assert not any(p.get("event", {}).get("event_type") == "arrived" for _, p in replay.b.poster.events)


@pytest.mark.parametrize("nav", [{"wz_mradps": 1000}, {"vx_mmps": 30}, {"flags": 0}, {"loc_state": 4}])
def test_goto_rejects_unqualified_navigation(replay, nav):
    replay.start()
    replay.run(nav=nav)
    assert replay.task.state != "completed"


@pytest.mark.parametrize("nav", [{"goal_x_mm": 9000, "x_mm": 0}, {"x_mm": 1800},
                               {"goal_x_mm": 1970, "x_mm": 1830}])
def test_final_goal_and_distance_are_rechecked(replay, nav):
    replay.start()
    replay.run(nav=nav)
    assert replay.task.state == "failed"


def test_goto_requires_advancing_feedback_and_arrival_hold(replay):
    replay.start()
    replay.run(seconds=.2)
    assert replay.task.state != "completed"
    assert any(p.get("task_status", {}).get("phase") == "verifying_arrival" for _, p in replay.b.poster.events)
    replay.b.runner.on_tick(replay.b.status_view(101.0), None, 101.0)
    assert replay.task.state != "completed"  # polling an old frame is not a hold
    replay.run(start=101.1, seconds=.7)
    assert replay.task.state == "completed"


def test_duplicate_arrived_status_cannot_finish_a_hold(replay):
    replay.start()
    replay.nav(100.4, state=2)
    frozen = replay.b.status
    for i in range(70):
        now = 100.4+i*.02
        replay.b._on_message(frozen, now)
        replay.control(now)
        replay.b.runner.on_tick(replay.b.status_view(now), None, now)
    assert replay.b.status_at == 100.4
    assert replay.task.state != "completed"
    assert not replay.b.status_view(102.).fresh


@pytest.mark.parametrize("command,state", [("pause_task", "paused"), ("cancel_task", "cancelled")])
def test_request_wording_and_later_stop_confirmation(replay, command, state):
    replay.start()
    replay.run(seconds=.7, nav={"mode": 1, "state": 1, "x_mm": 0})
    response = replay.command(command, 101.2)
    assert replay.task.state == state and replay.task.phase == "waiting_stop"
    assert "已停车" not in response["detail"]
    assert "尚未确认" in response["detail"] or "等待反馈" in response["detail"]
    replay.run(start=101.21, seconds=.2, control={"left_cms": 10}, nav={"state": 0})
    assert replay.task.phase == "waiting_stop"
    replay.run(start=101.43, seconds=.7, nav={"state": 0})
    assert replay.task.state == state and replay.task.phase == state
    assert "反馈已满足停稳条件" in replay.task.detail


def test_follow_timeout_waits_for_stop_and_fails_without_it(replay):
    replay.start("follow_target", timeout_s=1)
    replay.run(start=101.1, seconds=.2, control={"left_cms": 10}, nav={"mode": 2, "state": 1})
    assert replay.task.state == "running" and replay.task.phase == "waiting_stop"
    replay.run(start=101.32, seconds=.7, nav={"state": 0})
    assert replay.task.state == "completed"


def test_stop_request_timeout_keeps_failure_explicit(replay):
    replay.start("follow_target", timeout_s=1)
    replay.run(start=101.1, seconds=10.2, control=False, nav={"state": 0})
    assert replay.task.state == "failed" and replay.task.phase == "stop_unconfirmed"
    assert "未能确认停稳" in replay.task.detail


def test_resume_during_patrol_dwell_stop_wait(replay):
    replay.start()
    replay.task.dwell_until, replay.task.phase = 102., "dwell"
    assert replay.command("pause_task", 100.4)["accepted"]
    assert replay.task.phase == "waiting_stop"
    assert replay.command("resume_task", 100.41)["accepted"]
    replay.nav(100.42, mode=0, state=2)
    replay.b.runner.on_tick(replay.b.status_view(100.42), None, 100.42)
    assert replay.task.phase == "sending_goal" and replay.task.stop_requested_at is None


def test_cancel_during_follow_timeout_wait_stays_cancelled(replay):
    replay.start("follow_target", timeout_s=1)
    replay.run(start=101.1, seconds=.2, control=False)
    assert replay.task.finish_after_stop
    assert replay.command("cancel_task", 101.32)["accepted"]
    replay.run(start=101.34, seconds=.7, nav={"state": 0})
    assert replay.task.state == "cancelled" and replay.task.finish_after_stop is None


def test_follow_already_timed_out_cannot_be_resumed_by_pause(replay):
    replay.start("follow_target", timeout_s=1)
    replay.run(start=101.1, seconds=.2, control=False)
    assert not replay.command("pause_task", 101.32)["accepted"]
    assert replay.task.phase == "waiting_stop" and replay.task.finish_after_stop


@pytest.mark.parametrize("control,nav", [({"left_cms": 10}, {}), ({"wz_q12": 4096}, {}),
                                       (False, {}), ({"sensor_error": 1}, {}), ({}, {"wz_mradps": 1000}),
                                       ({}, {"loc_state": 4})])
def test_search_requires_measured_stop_and_zero_commands(replay, control, nav):
    replay.start("search_target")
    replay.run(target=True, control=control, nav=nav)
    assert replay.task.state != "completed"


def test_search_positive_with_continuous_good_evidence(replay):
    replay.start("search_target")
    replay.run(target=True)
    assert replay.task.state == "completed"


def test_intermediate_motion_and_sequence_gap_reset_evidence():
    evidence = StopEvidence()
    def sample(seq, stamp, **kw):
        return tm.decode_packet(tm.encode_frame(dict(sequence=seq, timestamp_ms=stamp,
                                status=tm.ST_BMI_READY, **kw)))
    for i in range(31):
        evidence.ingest(sample(i, 1000+i*20), 10+i*.02)
    assert evidence.view(10.6).stopped
    evidence.ingest(sample(31, 1620, left_delta=1), 10.62)
    evidence.ingest(sample(32, 1640), 10.64)
    assert not evidence.view(10.64).stopped
    evidence.ingest(sample(34, 1660), 10.66)
    assert evidence.quiet_since == 10.66
    # Increasing sequence with a frozen device timestamp is still a duplicate measurement.
    assert not evidence.ingest(sample(35, 1660), 10.68)
    assert evidence.received_at == 10.66


def test_backward_status_quarantines_then_recovers_forward_stream(replay):
    replay.start()
    replay.control(100.3)
    accepted = replay.b.status
    replay.nav(100.4, t_us=100000)
    assert replay.b.status is accepted and not replay.b.status_view(100.4).fresh
    assert replay.b.nv_control is None
    replay.control(100.4, timestamp_ms=100)  # cannot restore health in quarantine
    assert replay.b.platform_status(100.4)["control_link"] == "offline"
    replay.nav(100.5, mode=1, state=1)
    assert replay.b.status_view(100.5).fresh
    assert replay.b.stop_evidence.quiet_since is None


def test_confirmed_clock_rebase_ends_old_task(replay):
    replay.start()
    from yuntuo.fpga_link.nvmp import build_test_package, parse_package
    replay.b.prior_map = parse_package(build_test_package(0, 0, [[0]]))
    replay.nav(100.4, t_us=100000)
    replay.nav(100.6, t_us=300000)
    replay.nav(102., t_us=1700000)
    assert replay.task.state == "failed"
    assert replay.task.stop_requested_at is None  # no implicit IDLE/unlock on reset
    assert replay.b.status.t_us == 1700000 and replay.b.status_view(102.).fresh
    assert replay.b.prior_map is None and not replay.b.outbox


def test_timer_wrap_is_forward_progress(replay):
    replay.nav(100., t_us=0xFFFFFFF0)
    replay.nav(100.0001, t_us=84)
    assert replay.b.status.t_us == 84 and not replay.b.status_quarantined


def test_legacy_input_retains_intermediate_bad_sample(replay):
    class Reader:
        rate = RateMeter()
        def __init__(self):
            self.samples = []
        def drain(self):
            samples, self.samples = self.samples, []
            return samples
    reader = Reader()
    replay.b.nv_control_seen = False
    replay.b.telemetry = reader
    for i in range(31):
        stamp = 100.+i*.02
        frame = tm.decode_packet(tm.encode_frame(dict(sequence=i, timestamp_ms=round(stamp*1000),
                                                      status=tm.ST_BMI_READY)))
        reader.samples.append((frame, stamp))
    replay.nav(100.6)
    assert replay.b.status_view(100.6).motion.stopped
    # These arrive in one drain: a latest-only reader would silently lose the fault.
    for i in (31, 32):
        stamp = 100.+i*.02
        frame = tm.decode_packet(tm.encode_frame(dict(sequence=i, timestamp_ms=round(stamp*1000),
                                                      status=tm.ST_BMI_READY, sensor_error=int(i == 31))))
        reader.samples.append((frame, stamp))
    replay.nav(100.64)
    assert not replay.b.status_view(100.64).motion.stopped
