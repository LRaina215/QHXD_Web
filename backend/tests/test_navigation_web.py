from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app


def test_navigation_map_and_snapshot_round_trip() -> None:
    with TestClient(app) as client:
        map_payload = {
            "map_id": "test-map",
            "version": "test-v1",
            "frame_id": "map",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resolution": 0.05,
            "width": 3,
            "height": 2,
            "origin": {"x": -1.0, "y": -2.0, "yaw": 0.0},
            "data": [0, 100, -1, 0, 0, 100],
        }
        response = client.post("/api/internal/navigation/map", json=map_payload)
        assert response.status_code == 200

        metadata = client.get("/api/navigation/map/metadata")
        assert metadata.status_code == 200
        assert metadata.json()["data"]["version"] == "test-v1"

        image = client.get("/api/navigation/map/image")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": 7,
            "map_version": "test-v1",
            "pose": {"x": 1.0, "y": 2.0, "yaw": 0.5},
            "global_path": [{"x": 1.0, "y": 2.0}, {"x": 2.0, "y": 3.0}],
            "nav_state": "navigating",
            "remaining_distance": 1.414,
        }
        response = client.post("/api/internal/navigation/state", json=snapshot)
        assert response.status_code == 200

        latest = client.get("/api/navigation/latest")
        assert latest.status_code == 200
        assert latest.json()["data"]["sequence"] == 7

        with client.websocket_connect("/ws/navigation") as websocket:
            message = websocket.receive_json()
            assert message["type"] == "navigation"
            assert message["data"]["pose"]["x"] == 1.0
