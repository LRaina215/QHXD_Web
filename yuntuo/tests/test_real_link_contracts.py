"""Finite software contracts for the PNR61 protocol; no device access."""
from collections import Counter, deque
import math
import struct
import zlib

import pytest

from yuntuo.bridge.config import BridgeConfig
from yuntuo.bridge.core import FpgaBridge, PendingRequest
from yuntuo.bridge.poster import ListPoster
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link import telemetry as tm
from yuntuo.fpga_link.nvmp import HDR, MapPackageError, build_test_package, parse_package


class Clock:
    t = 1000.
    def __call__(self):
        return self.t


class AckLink:
    """Actual bytes at the API; CPU parsing/lease are explicit substitutes."""
    def __init__(self, clock, *, kind="uart", verdict=2, terminal=True):
        self.clock, self.kind, self.reliable = clock, kind, kind == "uart"
        self.verdict, self.terminal = verdict, terminal
        self.sent, self.queue, self.count = [], deque(), Counter()
        self.received = bytearray()
        self.rx_at, self.max_gap, self.next_status = clock(), 0., clock()
        self.drop = True
        self.mode = 4
        self.inject = None

    def send(self, data):
        self.max_gap = max(self.max_gap, self.clock() - self.rx_at)
        self.rx_at = self.clock()
        self.sent.append(data)
        kind = data[3]
        self.count[kind] += 1
        if kind == nv.MODE:
            self.mode = data[4]
        elif kind == nv.MAP_BEGIN:
            self.total = struct.unpack_from("<I", data, 4)[0]
            self.received.clear()
            if not self.drop or self.count[kind] > 1:
                self.queue.append(nv.encode_map_ack(0, 1))
        elif kind == nv.MAP_DATA:
            offset = struct.unpack_from("<I", data, 4)[0]
            key = (kind, offset)
            self.count[key] += 1
            if offset == len(self.received):
                self.received.extend(data[8:])
            else:
                assert offset < len(self.received)
            if not self.drop or self.count[key] > 1:
                self.queue.extend([nv.encode_map_ack(len(self.received) + 9999, 1),
                                   nv.encode_map_ack(len(self.received), 1)])
            if self.inject:
                self.inject()
                self.inject = None
        elif kind == nv.MAP_END:
            assert len(self.received) == self.total
            self.queue.append(nv.encode_map_ack(len(self.received), 1))
            if self.terminal and (not self.drop or self.count[kind] > 1):
                self.queue.append(nv.encode_map_ack(len(self.received), self.verdict))

    def recv(self, timeout=0.2):
        if self.queue:
            return self.queue.popleft()
        self.clock.t += max(timeout, .001)
        if self.clock() >= self.next_status:
            self.next_status = self.clock() + .2
            return nv.encode_status(nv.NavStatus(self.mode, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                                  0, round(self.clock() * 1e6) & 0xFFFFFFFF, 1, 0))
        return None

    def close(self):
        pass


def bridge_with(link, clock):
    return FpgaBridge(BridgeConfig(link=f"{link.kind}:test"),
                      link_factory=lambda: link, clock=clock, poster=ListPoster())


@pytest.mark.parametrize("kind", ["uart", "udp"])
def test_all_links_keep_lease_without_implicitly_unlocking(kind):
    clock = Clock()
    link = AckLink(clock, kind=kind)
    b = bridge_with(link, clock)
    b.tick()
    assert link.mode == 4 and not any(m[3] == nv.MODE for m in link.sent)
    b._handle_request(PendingRequest("estop", {"engage": False}), clock())
    b.tick()
    assert link.mode == 0
    # Ten simulated minutes, rather than pretending this is a real soak.
    end = clock() + 600
    while clock() < end:
        clock.t += .02
        b.tick()
    assert link.mode == 0 and link.max_gap < .15
    assert sum(m[3] == nv.MODE for m in link.sent) == 1
    b._drop_link(OSError("unplug"), clock())
    clock.t += 3
    link.mode = 4
    b.tick()
    assert link.mode == 4 and sum(m[3] == nv.MODE for m in link.sent) == 1


@pytest.mark.parametrize("kind", ["uart", "udp"])
@pytest.mark.parametrize("verdict", [2, 3, 4])
def test_map_requires_application_progress_and_terminal_ACK(kind, verdict):
    clock = Clock()
    link = AckLink(clock, kind=kind, verdict=verdict)
    link.mode = 0
    b = bridge_with(link, clock)
    b._ensure_link(clock())
    pkg = build_test_package(0, 0, [[0] * 64 for _ in range(64)], n_struct=16384)
    assert len(pkg) == 86064
    assert b._upload_map(pkg, parse_package(pkg)) == (verdict == 2)
    assert link.received == pkg and link.count[nv.MAP_BEGIN] == 2 and link.count[nv.MAP_END] == 2
    assert link.max_gap < .15  # Heartbeat continues during missing-ACK waits.


def test_loc_state_or_receive_ACK_cannot_replace_terminal_ACK():
    clock = Clock()
    link = AckLink(clock, terminal=False)
    link.mode = 0
    b = bridge_with(link, clock)
    b._ensure_link(clock())
    pkg = build_test_package(0, 0, [[0]])
    assert not b._upload_map(pkg, parse_package(pkg))
    assert b.prior_map is None and b.link is None


def test_ready_map_is_loaded_while_firmware_waits_for_initial_pose():
    clock = Clock()
    link = AckLink(clock)
    link.drop = False
    link.mode = 0
    b = bridge_with(link, clock)
    b._ensure_link(clock())
    pkg = build_test_package(0, 0, [[0]])
    assert b._upload_map(pkg, parse_package(pkg))
    b.status = nv.NavStatus(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1000000, 0, 0)
    b.status_at = clock()
    status = b.platform_status(clock())
    assert status["map_loaded"] is True and status["loc_state"] == "mapless"
    b._handle_request(PendingRequest("map", {"clear": True}), clock())
    assert b.platform_status(clock())["map_loaded"] is False


def test_unplug_invalidates_recent_feedback_and_valid_data_restores_it(monkeypatch):
    from types import SimpleNamespace
    from yuntuo.bridge import inputs

    clock = Clock()
    monkeypatch.setattr(inputs.time, "monotonic", clock)
    reader = inputs.TelemetryReader("serial:/test")
    reader._ingest(tm.encode_frame({"status": tm.ST_BMI_READY, "sequence": 1}))
    link = AckLink(clock)
    b = bridge_with(link, clock)
    b.telemetry = reader
    b.status = nv.NavStatus(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1000000, 0, 0)
    b.status_at = clock()
    assert b.platform_status(clock())["control_link"] == "online"

    class Unplugged:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, _):
            raise OSError("device disconnected")

    def end_after_retry_delay(_):
        raise KeyboardInterrupt

    monkeypatch.setitem(__import__("sys").modules, "serial", SimpleNamespace(Serial=lambda *a, **kw: Unplugged()))
    monkeypatch.setattr(inputs.time, "sleep", end_after_retry_delay)
    with pytest.raises(KeyboardInterrupt):
        reader.run()
    # No fake passage of the one-second display timeout: the OS failure alone
    # invalidates the still-recent frame and its stop evidence.
    assert b.platform_status(clock())["control_link"] == "offline"
    assert not b.platform_status(clock())["control_telemetry"]["fresh"]
    assert not b.status_view(clock()).motion.ready
    reader._ingest(tm.encode_frame({"status": tm.ST_BMI_READY, "sequence": 2}))
    assert b.platform_status(clock())["control_link"] == "online"


def test_estop_preempts_map_wait_and_cannot_be_followed_by_old_goal():
    clock = Clock()
    link = AckLink(clock)
    link.mode = 0
    b = bridge_with(link, clock)
    b._ensure_link(clock())
    req = PendingRequest("estop", {"engage": True})
    blocked = PendingRequest("mission", {"command": "go_to_waypoint", "payload": {"waypoint_id": "home"}})
    def inject():
        b.requests.put(blocked)
        b.requests.put(req)
    link.inject = inject
    pkg = build_test_package(0, 0, [[0]])
    assert not b._upload_map(pkg, parse_package(pkg))
    assert req.ready.is_set() and req.response["data"]["accepted"]
    assert not blocked.response["data"]["accepted"]
    assert link.mode == 4 and link.sent[-1] == nv.encode_mode("estop")
    assert b.link is not None and b.prior_map is None


def test_stop_discards_queued_motion_before_the_next_IO():
    clock = Clock()
    link = AckLink(clock)
    b = bridge_with(link, clock)
    b._ensure_link(clock())
    b._send(nv.encode_goal(1200, 300))
    b._send(nv.encode_target(700, 0, found=True))
    b._send(nv.encode_mode("idle"), urgent=True)
    b._io(clock(), recv=False)
    assert link.sent == [nv.encode_mode("idle")]


@pytest.mark.parametrize("pitch,roll", [(4.33, -8.63), (10, 0), (-10, 0), (0, 10), (0, -10)])
def test_control_body_axes_match_navigation_attitude(pitch, roll):
    p, r = math.radians(pitch), math.radians(roll)
    f = tm.decode_packet(tm.encode_frame({"status": tm.ST_BMI_READY,
        "gravity_x_q12": round(math.sin(r) * math.cos(p) * 4096),
        "gravity_y_q12": round(math.sin(p) * 4096),
        "gravity_z_q12": round(-math.cos(r) * math.cos(p) * 4096)}))
    assert abs(f.pitch_deg - pitch) < .02 and abs(f.roll_deg - roll) < .02


@pytest.mark.parametrize("offset,fmt,value", [(4, "H", 2), (6, "H", 0x108), (16, "I", 16385),
    (28, "H", 65), (30, "H", 65), (40, "I", 0), (44, "h", 349), (46, "h", -299)])
def test_current_map_contract_rejects_legacy_and_incompatible_geometry(offset, fmt, value):
    pkg = bytearray(build_test_package(0, 0, [[0]]))
    struct.pack_into("<" + fmt, pkg, offset, value)
    with pytest.raises(MapPackageError):
        parse_package(pkg)


@pytest.mark.parametrize("slot,word", [(16384, 0), (65535, 0), (0, 0x40000)])
def test_current_map_contract_checks_each_structure_word(slot, word):
    pkg = bytearray(build_test_package(0, 0, [[0]], n_struct=1))
    pkg[HDR.size:HDR.size + 5] = struct.pack("<H", slot) + word.to_bytes(3, "little")
    struct.pack_into("<I", pkg, 32, zlib.crc32(pkg[HDR.size:]))
    with pytest.raises(MapPackageError):
        parse_package(pkg)


def test_current_map_rejects_trailing_data_even_with_valid_body_CRC():
    pkg = build_test_package(0, 0, [[0]])
    with pytest.raises(MapPackageError):
        parse_package(pkg + b"extra")
