"""Real HTTP/backend/bridge code with an explicit byte-level FPGA ACK substitute."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.map_upload import MAX_MAP_BYTES, map_upload_service
from app.services.state_store import state_store
from yuntuo.bridge.core import PendingRequest
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link.nvmp import build_test_package
from yuntuo.tests.test_real_link_contracts import AckLink, Clock, bridge_with


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("YUNTUO_MAP_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("YUNTUO_MAP_PREVIEW_FILE", str(tmp_path / "preview.json"))
    monkeypatch.setattr(map_upload_service, "preview_map", None)
    monkeypatch.setattr(state_store, "get_system_mode", lambda: SimpleNamespace(mode="real"))
    clock = Clock()
    link = AckLink(clock)
    link.mode = 0
    b = bridge_with(link, clock)
    b.tick()
    def bridge(path, payload=None):
        return b.snapshot() if path == "/health" else b._handle_request(PendingRequest("map", payload), clock())
    monkeypatch.setattr(map_upload_service, "_bridge", bridge)
    return TestClient(app), b, link, clock, tmp_path


def post(client, data=None, filename="field.nvmp", map_id="yuntuo_field", preview=False, **kwargs):
    return client.post("/api/navigation/map/upload", params={"filename": filename, "map_id": map_id, "preview": preview},
                       content=data if data is not None else build_test_package(0, 0, [[0, 254], [255, 0]]),
                       headers=kwargs.pop("headers", {"Content-Type": "application/octet-stream"}), **kwargs)


def test_web_bytes_to_queue_to_terminal_ready_and_reset(rig):
    c, b, link, clock, folder = rig
    pkg = build_test_package(0, 0, [[0, 254], [255, 0]])
    r = post(c, pkg)
    assert r.status_code == 200 and r.json()["data"]["state"] == "queued"
    uid = r.json()["data"]["id"]
    assert (folder / f"{uid}.nvmp").read_bytes() == pkg
    observed = []
    link.inject = lambda: observed.append(dict(b.map_upload))
    b.tick()
    assert link.received == pkg and observed[0]["progress"] < 100
    clock.t += 1 / b.cfg.platform_post_hz + .01  # Wait for the configured public snapshot cadence.
    b.tick()
    result = c.get("/api/navigation/map/upload").json()["data"]
    assert (result["state"], result["progress"], result["id"]) == ("ready", 100, uid)
    assert not any(m[3] == nv.MODE for m in link.sent)  # No automatic IDLE/rearm.
    # Runtime stop does not turn a previously loaded map into a cancelled upload.
    b._handle_request(PendingRequest("estop", {"engage": True}), clock())
    assert b.map_upload["state"] == "ready"
    # Confirmed FPGA clock rollback invalidates the prior and its upload status.
    old = b.status
    clock.t += 4
    for stamp in (10000, 210000):
        b._on_message(nv.NavStatus(4, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, stamp, 0, 0), clock())
        clock.t += .2
    assert old is not None and b.prior_map is None and b.map_upload["state"] == "invalidated"


@pytest.mark.parametrize("verdict,terminal", [(3, True), (4, True), (2, False)])
def test_only_ready_end_succeeds(rig, verdict, terminal):
    c, b, link, clock, folder = rig
    link.verdict, link.terminal = verdict, terminal
    assert post(c).status_code == 200
    b.tick()
    assert b.map_upload["state"] == "failed" and b.map_upload["progress"] < 100
    assert b.prior_map is None


def test_estop_interrupts_transfer_and_old_motion_never_follows(rig):
    c, b, link, clock, folder = rig
    pkg = build_test_package(0, 0, [[0] * 30 for _ in range(30)])
    assert post(c, pkg).status_code == 200
    link.inject = lambda: b.requests.put(PendingRequest("estop", {"engage": True}))
    b.tick()
    assert b.map_upload["state"] == "cancelled" and b.prior_map is None
    assert not any(m[3] == nv.MAP_END for m in link.sent)


def test_busy_offline_and_paused_task_do_not_overwrite_queue(rig):
    c, b, link, clock, folder = rig
    first = post(c)
    assert first.status_code == 200
    assert post(c).status_code == 409 and b.map_upload["id"] == first.json()["data"]["id"]
    b.pending_map = None
    b.runner.task = SimpleNamespace(active=True)
    assert post(c).status_code == 409
    b.runner.task = None
    b.status_quarantined = True
    assert post(c).status_code == 409
    assert len(list(folder.glob("*.nvmp"))) == 1


@pytest.mark.parametrize("kind", ["CRC", "profile", "legacy", "slot", "word", "truncated", "extension", "path", "map_id"])
def test_reject_bad_content_and_names_before_queue(rig, kind):
    c, b, link, clock, folder = rig
    import struct
    import zlib
    from yuntuo.fpga_link.nvmp import HDR
    data = bytearray(build_test_package(0, 0, [[0]], n_struct=1))
    args = {}
    if kind == "CRC": data[-1] ^= 1
    elif kind == "profile": struct.pack_into("<I", data, 40, 0)
    elif kind == "legacy": struct.pack_into("<H", data, 4, 2)
    elif kind in ("slot", "word"):
        if kind == "slot": struct.pack_into("<H", data, HDR.size, 16384)
        else: data[HDR.size + 4] = 4
        struct.pack_into("<I", data, 32, zlib.crc32(data[HDR.size:]))
    elif kind == "truncated": data.pop()
    elif kind == "extension": args["filename"] = "field.png"
    elif kind == "path": args["filename"] = "../field.nvmp"
    elif kind == "map_id": args["map_id"] = "../bad"
    r = post(c, bytes(data), **args)
    assert r.status_code == 422 and b.pending_map is None and not list(folder.iterdir())


def test_limit_stream_even_when_declared_length_is_small(rig):
    c, b, link, clock, folder = rig
    r = post(c, b"x" * (MAX_MAP_BYTES + 1), headers={"Content-Type": "application/octet-stream", "Content-Length": "1"})
    assert r.status_code == 413 and b.pending_map is None
    assert post(c, headers={"Content-Type": "image/png"}).status_code == 415


def test_mock_and_bridge_unavailable_are_explicit(rig, monkeypatch):
    c, b, link, clock, folder = rig
    monkeypatch.setattr(state_store, "get_system_mode", lambda: SimpleNamespace(mode="mock"))
    assert post(c).status_code == 409
    assert c.get("/api/navigation/map/upload").json()["data"]["state"] == "unavailable"


def test_preview_is_PNG_and_never_changes_live_navigation_or_FPGA(rig, monkeypatch):
    import base64
    import struct
    from app.services.navigation_store import navigation_store
    c, b, link, clock, folder = rig
    before = navigation_store.map_metadata()
    monkeypatch.setattr(state_store, "get_system_mode", lambda: SimpleNamespace(mode="mock"))
    r = post(c, preview=True)
    assert r.status_code == 200
    m = r.json()["data"]
    assert m["kind"] == "preview" and m["version"].startswith("preview-")
    image = base64.b64decode(m["image_url"].split(",", 1)[1])
    assert image.startswith(b"\x89PNG") and struct.unpack_from(">II", image, 16) == (2, 2)
    assert b.pending_map is None and b.prior_map is None and link.count[nv.MAP_BEGIN] == 0
    assert navigation_store.map_metadata() == before
    map_upload_service.preview_map = None  # Recreate an empty process cache, preserving its saved preview.
    assert c.get("/api/navigation/map/upload?preview=true").json()["data"]["version"] == m["version"]


def test_actual_upload_exits_preview_only_after_bridge_acceptance(rig):
    c, b, link, clock, folder = rig
    assert post(c, preview=True).status_code == 200
    b.status_quarantined = True
    assert post(c).status_code == 409
    assert c.get("/api/navigation/map/upload?preview=true").json()["data"] is not None
    b.status_quarantined = False
    assert post(c).status_code == 200
    assert c.get("/api/navigation/map/upload?preview=true").json()["data"] is None


def test_empty_costmap_preview_is_rejected(rig):
    c, b, link, clock, folder = rig
    assert post(c, build_test_package(0, 0, []), preview=True).status_code == 422
    assert b.pending_map is None
