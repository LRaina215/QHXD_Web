"""fpga_bridge 任务状态机 + mock_fpga 仿真核心，单线程、仿真时钟，确定性运行。"""
import json
import math

import pytest

from yuntuo.bridge.config import BridgeConfig
from yuntuo.bridge.core import FpgaBridge, PendingRequest
from yuntuo.bridge.inputs import DetectionFrame
from yuntuo.bridge.poster import ListPoster
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link.nvmp import build_test_package
from yuntuo.mock_fpga import MockFpgaCore, default_world


class SimClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SimLink:
    kind = "sim"
    reliable = True

    def __init__(self, core, clock):
        self.core, self.clock = core, clock
        self.replies, self.sent = [], []
        self.next_status = 0.0
        self.alive = True

    def send(self, msg):
        if not self.alive:
            return
        self.sent.append(msg)
        self.replies += self.core.handle(msg, self.clock())

    def recv(self, timeout=0.2):
        if not self.alive:
            return None
        if self.replies:
            return self.replies.pop(0)
        now = self.clock()
        if now >= self.next_status:
            self.next_status = now + 0.2
            return nv.encode_status(self.core.status(now))
        return None

    def close(self):
        pass


class SimPerception:
    def __init__(self, core, clock, world):
        self.core, self.clock, self.world = core, clock, world
        self.frame, self.next_at, self.enabled = None, 0.0, True

    def update(self):
        now = self.clock()
        if self.enabled and now >= self.next_at:
            self.next_at = now + 0.1
            self.frame = DetectionFrame(seq=0, stamp_mono=now - 0.05, stamp_wall=None, received_mono=now,
                                        objects=self.core.observe(self.world, now))

    def latest(self):
        return self.frame


@pytest.fixture
def sim(tmp_path):
    (tmp_path / "wp.json").write_text(json.dumps([
        {"waypoint_id": "home", "name": "起点", "pose": [0.0, 0.0, 0.0], "enabled": True},
        {"waypoint_id": "wp_a", "name": "A 点", "pose": [2.0, 1.0, 0.0], "enabled": True},
        {"waypoint_id": "wp_b", "name": "B 点", "pose": [3.0, -1.0, 0.0], "enabled": True},
        {"waypoint_id": "wp_off", "name": "禁用点", "pose": [1.0, 1.0, 0.0], "enabled": False},
    ]), encoding="utf-8")
    (tmp_path / "routes.json").write_text(json.dumps([
        {"route_id": "default_patrol", "waypoints": ["wp_a", "wp_b"], "stop_seconds": 1, "return_home": True},
    ]), encoding="utf-8")
    cfg = BridgeConfig(waypoints_path=tmp_path / "wp.json", routes_path=tmp_path / "routes.json")
    clock = SimClock()
    core = MockFpgaCore(seed=3)
    core.t0 = clock.t
    link = SimLink(core, clock)
    perception = SimPerception(core, clock, default_world())
    poster = ListPoster()
    bridge = FpgaBridge(cfg, link_factory=lambda: link, clock=clock, poster=poster, perception=perception)

    class Sim:
        pass

    s = Sim()
    s.bridge, s.core, s.clock, s.link, s.poster, s.perception, s.tmp = bridge, core, clock, link, poster, perception, tmp_path

    def run(seconds, until=None):
        for _ in range(int(seconds / 0.02)):
            clock.t += 0.02
            core.step(0.02, clock.t)
            perception.update()
            bridge.tick()
            if until is not None and until():
                return True
        return False

    def command(command, **payload):
        req = PendingRequest("mission", {"command": command, "source": "test", "payload": payload})
        resp = bridge._handle_request(req, clock.t)
        return resp["data"]

    def events():
        return [p["event"]["event_type"] for path, p in poster.events if path == "/api/internal/mission/update"]

    s.run, s.command, s.events = run, command, events
    return s


def task_state(s):
    return s.bridge.runner.task.state if s.bridge.runner.task else None


def test_rejects_until_fpga_status_arrives(sim):
    r = sim.command("go_to_waypoint", waypoint_id="wp_a")
    assert not r["accepted"] and "STATUS" in r["detail"]
    sim.run(0.5)
    assert not sim.command("go_to_waypoint", waypoint_id="wp_off")["accepted"]
    assert not sim.command("start_patrol", patrol_id="nope")["accepted"]
    assert not sim.command("dance")["accepted"]


def test_go_to_waypoint_reaches_goal_and_reports(sim):
    sim.run(0.5)
    r = sim.command("go_to_waypoint", waypoint_id="wp_a")
    assert r["accepted"] and r["task_status"]["task_type"] == "go_to_waypoint"
    assert set(r) == {"accepted", "command", "task_status", "current_goal", "nav_state", "received_at", "detail"}
    sim.run(0.02)
    assert sim.link.sent[-1] == nv.encode_goal(2000, 1000)
    assert sim.run(30, until=lambda: task_state(sim) == "completed")
    assert math.hypot(sim.core.x - 2.0, sim.core.y - 1.0) < 0.2
    ev = sim.events()
    assert ev[0] == "started" and ev[-2:] == ["arrived", "completed"]
    path, snap = sim.poster.latest["nav"]
    assert path == "/api/internal/navigation/state" and snap["source"] == "fpga_bridge"
    assert abs(snap["pose"]["x"] - sim.core.x) < 0.1
    sim.run(1.0)
    _, plat = sim.poster.latest["platform"]
    assert plat["platform_status"]["nav_link"] == "online"
    assert plat["platform_status"]["fpga_state"] == "arrived"
    assert sim.poster.latest["map"][1]["version"].startswith("canvas")


def test_patrol_dwells_and_returns_home(sim):
    sim.run(0.5)
    assert sim.command("start_patrol", patrol_id="default_patrol")["accepted"]
    assert sim.run(90, until=lambda: task_state(sim) == "completed")
    assert sim.events().count("arrived") == 3
    assert math.hypot(sim.core.x, sim.core.y) < 0.2


def test_pause_resume_cancel(sim):
    sim.run(0.5)
    sim.command("go_to_waypoint", waypoint_id="wp_b")
    sim.run(2.0)
    assert sim.command("pause_task")["accepted"]
    sim.run(0.04)
    assert sim.core.mode == 0 and task_state(sim) == "paused"
    x_paused = sim.core.x
    sim.run(2.0)
    assert abs(sim.core.x - x_paused) < 0.05
    assert not sim.command("go_to_waypoint", waypoint_id="wp_a")["accepted"]
    assert sim.command("resume_task")["accepted"]
    sim.run(2.0)
    assert sim.core.mode == 1 and task_state(sim) == "running"
    assert sim.command("cancel_task")["accepted"]
    sim.run(0.04)
    assert sim.core.mode == 0 and task_state(sim) == "cancelled"
    assert sim.events()[-1] == "cancelled"


def test_search_red_bottle_stops_near_it(sim):
    sim.run(0.5)
    r = sim.command("search_target", target_class="水瓶", color="红色", label="红色水瓶", timeout_s=120)
    assert r["accepted"] and r["current_goal"] == "target:红色水瓶"
    assert sim.run(120, until=lambda: task_state(sim) in ("completed", "failed"))
    assert task_state(sim) == "completed", sim.bridge.runner.task.detail
    red = default_world()[0]
    d = math.hypot(sim.core.x - red.x, sim.core.y - red.y)
    assert 0.5 < d < 1.05
    assert sim.core.mode == 0
    sent_targets = [nv.decode_host(m) for m in sim.link.sent if m[3] == nv.TARGET]
    assert sent_targets and all(t.fields["cls"] == 39 and t.fields["latency_ms"] <= 400 for t in sent_targets)
    assert "arrived" in sim.events()


def test_search_unknown_target_times_out(sim):
    sim.run(0.5)
    sim.command("search_target", target_class="cup", timeout_s=15)
    sim.run(20)
    assert task_state(sim) == "failed" and sim.core.mode == 0
    assert not any(m[3] == nv.TARGET for m in sim.link.sent)


def test_follow_person_until_timeout(sim):
    sim.run(0.5)
    sim.command("follow_target", target_class="person", timeout_s=40)
    assert sim.run(40, until=lambda: sim.bridge.runner.task.phase == "tracking")
    sim.run(45)
    assert task_state(sim) == "completed" and sim.core.mode == 0


def test_estop_blocks_new_tasks(sim):
    sim.run(0.5)
    sim.command("go_to_waypoint", waypoint_id="wp_b")
    sim.run(1.0)
    resp = sim.bridge._handle_request(PendingRequest("estop", {"engage": True}), sim.clock.t)
    assert resp["data"]["accepted"]
    sim.run(0.5)
    assert sim.core.state == 6 and task_state(sim) == "failed"
    assert "急停" in sim.command("go_to_waypoint", waypoint_id="wp_a")["detail"]
    sim.bridge._handle_request(PendingRequest("estop", {"engage": False}), sim.clock.t)
    sim.run(0.5)
    assert sim.command("go_to_waypoint", waypoint_id="wp_a")["accepted"]


def test_link_loss_fails_active_task(sim):
    sim.run(0.5)
    sim.command("go_to_waypoint", waypoint_id="wp_b")
    sim.run(1.0)
    sim.link.alive = False
    sim.run(12)
    assert task_state(sim) == "failed" and "链路中断" in sim.bridge.runner.task.detail
    _, plat = sim.poster.latest["platform"]
    assert plat["platform_status"]["nav_link"] == "offline"


def test_prior_map_upload_and_localization_gate(sim):
    pkg = build_test_package(-10, -30, [[0] * 70 for _ in range(60)])
    (sim.tmp / "field.nvmp").write_bytes(pkg)
    resp = sim.bridge._handle_request(PendingRequest("map", {"path": str(sim.tmp / "field.nvmp")}), sim.clock.t)
    assert resp["data"]["accepted"]
    sim.run(0.5)
    assert sim.bridge.prior_map is not None and sim.core.map_loaded
    assert sim.poster.latest["map"][1]["width"] == 70
    assert "初始位姿" in sim.command("go_to_waypoint", waypoint_id="wp_a")["detail"]
    sim.bridge._handle_request(PendingRequest("set_pose", {"x": 0, "y": 0, "yaw": 0}), sim.clock.t)
    sim.run(2.5)
    assert sim.command("go_to_waypoint", waypoint_id="wp_a")["accepted"]
