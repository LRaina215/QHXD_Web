"""RK software-stage API check. Refuses writes unless BOTH FPGA links are mock.

This is not real-FPGA, browser, microphone or physical-stop acceptance. It is
safe to run while the physical FPGA remains in its unrelated hold image.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from yuntuo.fpga_link.nvmp import build_test_package, parse_package


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    rows, posts = [], []
    authorized = False
    error = None

    def get(port, path):
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return json.load(r)

    def mock_only():
        h = get(9101, "/health")
        p = h.get("platform") or {}
        assert h.get("link") == "udp:127.0.0.1:9000" and h.get("link_open")
        assert p.get("nav_link") == p.get("control_link") == "mock", p
        assert h.get("status_age_s") is not None and h["status_age_s"] < .8
        return h

    def post(port, path, body):
        mock_only()  # Recheck immediately before every write, including cleanup.
        req = Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=6) as r:
            result = json.load(r)
        posts.append({"port": port, "path": path, "response": result})
        return result

    def wait(label, predicate, timeout=6):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(.1)
        raise AssertionError("Timed out: " + label)

    def record(name, **data):
        rows.append(dict(case=name, passed=True, **data))
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    def accepted(port, path, body):
        result = post(port, path, body)
        assert result.get("success") and result["data"]["accepted"], result
        return result["data"]

    try:
        initial = mock_only()
        assert (initial.get("task") or {}).get("state") not in ("running", "pending", "paused")
        assert initial["platform"]["fpga_mode"] == "idle" and not initial["platform"]["control_estop"]
        authorized = True
        old_pose = get(8000, "/api/navigation/latest")["data"]["pose"]
        with tempfile.TemporaryDirectory(prefix="yuntuo_mock_api_") as td:
            folder = Path(td)
            pkg = build_test_package(-32, -32, [[0] * 64 for _ in range(64)], n_struct=16384)
            assert len(pkg) == 86064
            good = folder / "maximum-v3.nvmp"
            good.write_bytes(pkg)
            expected_version = parse_package(pkg).digest
            started = time.monotonic()
            # The configured waypoint set belongs to yuntuo_field. A different
            # package ID is correctly rejected by the later mission preflight.
            accepted(9101, "/api/internal/fpga/map", {"path": str(good), "map_id": "yuntuo_field"})
            h = wait("map READY", lambda: (h if (h := mock_only())["platform"]["map_loaded"] else None))
            meta = wait("map version", lambda: (m if (m := get(8000, "/api/navigation/map/metadata")["data"])
                                                   and m["version"] == expected_version else None))
            record("maximum_map_READY_and_backend_version", bytes=len(pkg), elapsed_s=time.monotonic() - started,
                   map_version=meta["version"], link="mock")
            for label, offset, fmt, value in [("CRC", 32, "I", 1), ("profile", 40, "I", 0)]:
                bad = bytearray(pkg)
                struct.pack_into("<" + fmt, bad, offset, value)
                path = folder / (label + ".nvmp")
                path.write_bytes(bad)
                result = post(9101, "/api/internal/fpga/map", {"path": str(path)})
                assert result["data"]["accepted"] is False, result
                record("bad_" + label + "_rejected", detail=result["data"]["detail"])
            accepted(8000, "/api/platform/set_pose", {"x": 1.25, "y": -.35, "yaw": .2, "align": True, "source": "web"})
            pose = wait("set pose", lambda: (p if (p := get(8000, "/api/navigation/latest")["data"]["pose"])
                                             and abs(p["x"] - 1.25) < .005 and abs(p["y"] + .35) < .005 else None))
            record("set_pose_backend_to_mock", pose=pose)
            accepted(9101, "/api/internal/fpga/map", {"clear": True})
            wait("mapless", lambda: mock_only()["platform"]["loc_state"] == "mapless")
            record("map_clear_returns_mapless")
            accepted(8000, "/api/mission/go_to_waypoint", {"waypoint_id": "wp_a", "source": "web"})
            wait("goto", lambda: mock_only()["platform"]["fpga_mode"] == "goto")
            result = accepted(8000, "/api/mission/pause", {"source": "web"})
            assert "已停车" not in result["detail"], result
            wait("paused", lambda: (mock_only().get("task") or {}).get("state") == "paused")
            accepted(8000, "/api/mission/resume", {"source": "web"})
            wait("resumed", lambda: mock_only()["platform"]["fpga_mode"] == "goto")
            accepted(8000, "/api/mission/cancel", {"source": "web"})
            wait("cancelled idle", lambda: mock_only()["platform"]["fpga_mode"] == "idle")
            record("goto_pause_resume_cancel", pause_detail=result["detail"])
            accepted(8000, "/api/mission/return_home", {"source": "web"})
            wait("return home", lambda: mock_only()["platform"]["fpga_mode"] == "goto")
            accepted(8000, "/api/mission/cancel", {"source": "web"})
            wait("return cancelled", lambda: mock_only()["platform"]["fpga_mode"] == "idle")
            record("return_home_cancel")
            accepted(8000, "/api/platform/estop", {"engage": True, "source": "web"})
            wait("ESTOP", lambda: mock_only()["platform"]["fpga_mode"] == "estop")
            time.sleep(.4)
            assert mock_only()["platform"]["fpga_mode"] == "estop"  # heartbeats do not release it
            accepted(8000, "/api/platform/estop", {"engage": False, "source": "web"})
            wait("explicit idle", lambda: mock_only()["platform"]["fpga_mode"] == "idle")
            record("explicit_estop_and_release")
            state = get(8000, "/api/state/latest")["data"]
            assert state["device_status"]["battery_percent"] is None
            assert state["env_sensor"]["temperature_c"] is None and state["env_sensor"]["humidity_percent"] is None
            record("unmeasured_fields_null", device_status=state["device_status"], env_sensor=state["env_sensor"])
    except Exception as exc:
        error = repr(exc)
    finally:
        cleanup = None
        if authorized:
            try:
                h = mock_only()
                if (h.get("task") or {}).get("state") in ("running", "pending", "paused"):
                    post(8000, "/api/mission/cancel", {"source": "web"})
                if mock_only()["platform"]["fpga_mode"] == "estop":
                    post(8000, "/api/platform/estop", {"engage": False, "source": "web"})
                wait("cleanup idle", lambda: mock_only()["platform"]["fpga_mode"] == "idle")
                post(9101, "/api/internal/fpga/map", {"clear": True})
                if "old_pose" in locals() and old_pose:
                    post(8000, "/api/platform/set_pose", {**old_pose, "align": False, "source": "web"})
                cleanup = "mock idle/map cleared/initial pose requested"
            except Exception as exc:
                cleanup = repr(exc)
        result = dict(passed=error is None, error=error, ended_at=datetime.now(timezone.utc).isoformat(),
                      cases=rows, requests=posts, cleanup=cleanup,
                      scope="Actual RK backend/bridge and UDP mock only; not FPGA/Web UI/voice ASR/phone",
                      FPGA_access=False, JTAG_or_Flash_used=False)
        (a.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
        print(json.dumps({k: v for k, v in result.items() if k != "requests"}, ensure_ascii=False), flush=True)
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
