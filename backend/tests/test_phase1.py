import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import app.main as main_module
from app.schemas import (
    AlertEvent,
    DeviceStatus,
    EnvSensor,
    GoToWaypointRequest,
    ModeSwitchRequest,
    NavStatus,
    NucStateUpdateRequest,
    RobotPose,
    TaskStatus,
)
from app.services.mock_state import MockStateService
from app.services.persistence import persistence
from app.services.state_store import state_store


class Phase1BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = persistence._db_path
        self._original_service = main_module.mock_state_service

        persistence._db_path = Path(self._temp_dir.name) / "phase1-test.db"
        main_module.mock_state_service = MockStateService()
        main_module.mock_state_service.initialize()
        state_store.initialize(main_module.mock_state_service.get_latest_state())

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

    async def test_system_mode_switch_endpoint_updates_contract_state(self) -> None:
        response = await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        latest_state = state_store.get_latest_state()

        self.assertTrue(response.success)
        self.assertEqual(response.data.system_mode.mode, "real")
        self.assertEqual(latest_state.system_mode.mode, "real")

    async def test_nuc_state_ingest_updates_shared_state_in_real_mode(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )

        response = await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=12.3,
                    y=4.5,
                    yaw=1.2,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-001",
                    remaining_distance=3.2,
                ),
                task_status=TaskStatus(
                    task_id="task-real-001",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=35,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=77,
                    emergency_stop=False,
                    fault_code=None,
                    online=True,
                ),
                env_sensor=EnvSensor(
                    temperature_c=26.5,
                    humidity_percent=48.2,
                    status="nominal",
                ),
                alerts=[
                    AlertEvent(
                        alert_id="alert-real-001",
                        level="warning",
                        message="NUC state injected for test.",
                        source="nuc",
                        timestamp=datetime.now(timezone.utc),
                        acknowledged=False,
                    )
                ],
                updated_at=datetime.now(timezone.utc),
            )
        )
        latest_state = state_store.get_latest_state()
        alerts = persistence.list_recent_alerts()

        self.assertTrue(response.success)
        self.assertTrue(response.data.accepted)
        self.assertTrue(response.data.state_updated)
        self.assertEqual(latest_state.system_mode.mode, "real")
        self.assertEqual(latest_state.task_status.source, "nuc")
        self.assertEqual(latest_state.nav_status.current_goal, "wp-001")
        self.assertEqual(alerts[0].alert_id, "alert-real-001")

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
