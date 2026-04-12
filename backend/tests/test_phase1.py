import sqlite3
import tempfile
import unittest
from pathlib import Path

import app.main as main_module
from app.schemas import GoToWaypointRequest
from app.services.mock_state import MockStateService
from app.services.persistence import persistence


class Phase1BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = persistence._db_path
        self._original_service = main_module.mock_state_service

        persistence._db_path = Path(self._temp_dir.name) / "phase1-test.db"
        main_module.mock_state_service = MockStateService()
        main_module.mock_state_service.initialize()

    def tearDown(self) -> None:
        main_module.mock_state_service = self._original_service
        persistence._db_path = self._original_db_path
        self._temp_dir.cleanup()

    async def test_health_endpoint_returns_ok(self) -> None:
        response = await main_module.health()

        self.assertEqual(response.status, "ok")

    async def test_go_to_waypoint_endpoint_persists_command_log(self) -> None:
        request = GoToWaypointRequest(
            waypoint_id="mock-waypoint",
            source="test",
            requested_by="unittest",
        )

        response = await main_module.go_to_waypoint(request)
        logs = persistence.list_command_logs()

        self.assertTrue(response.success)
        self.assertEqual(response.data.command, "go_to_waypoint")
        self.assertEqual(response.data.task_status.task_type, "go_to_waypoint")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].source, "test")
        self.assertEqual(logs[0].payload["waypoint_id"], "mock-waypoint")

    def test_mock_state_tick_updates_snapshot_history(self) -> None:
        before = main_module.mock_state_service.get_latest_state()
        after = main_module.mock_state_service.tick()

        with sqlite3.connect(persistence.db_path) as connection:
            snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM state_snapshots"
            ).fetchone()[0]

        self.assertNotEqual(before.updated_at, after.updated_at)
        self.assertNotEqual(before.device_status.battery_percent, after.device_status.battery_percent)
        self.assertGreaterEqual(snapshot_count, 2)


if __name__ == "__main__":
    unittest.main()
