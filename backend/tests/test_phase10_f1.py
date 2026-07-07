import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import app.main as main_module
from app.schemas import (
    GoToWaypointRequest,
    MissionExecutorUpdateRequest,
    ModeSwitchRequest,
    TaskEvent,
    TaskStatus,
)
from app.services.mock_state import MockStateService
from app.services.mode_manager import mode_manager
from app.services.mission_gateway import MissionGateway
from app.services.persistence import persistence
from app.services.state_store import state_store
from app.services.waypoint_registry import WaypointRegistry


class Phase10F1Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_db = persistence._db_path
        self._old_preflight = os.environ.get("NAV_MISSION_PREFLIGHT_ENABLED")
        self._old_tts = os.environ.get("MISSION_EVENT_TTS_ENABLED")
        self._old_cboard_heartbeat = os.environ.get("ROS2_IMU_HEARTBEAT_FILE")
        self._old_waypoints_config = os.environ.get("WAYPOINTS_CONFIG_PATH")
        persistence._db_path = Path(self._temp_dir.name) / "phase10-f1.db"
        persistence.initialize()
        service = MockStateService()
        service.initialize()
        state_store.initialize(service.get_latest_state())
        mode_manager.initialize(state_store.get_latest_state())
        os.environ["MISSION_EVENT_TTS_ENABLED"] = "false"

    def tearDown(self) -> None:
        persistence._db_path = self._old_db
        self._restore("NAV_MISSION_PREFLIGHT_ENABLED", self._old_preflight)
        self._restore("MISSION_EVENT_TTS_ENABLED", self._old_tts)
        self._restore("ROS2_IMU_HEARTBEAT_FILE", self._old_cboard_heartbeat)
        self._restore("WAYPOINTS_CONFIG_PATH", self._old_waypoints_config)
        self._temp_dir.cleanup()

    def test_waypoint_registry_validates_pose_and_duplicate_alias(self) -> None:
        path = Path(self._temp_dir.name) / "waypoints.json"
        path.write_text(
            json.dumps([
                {
                    "waypoint_id": "home",
                    "name": "起点",
                    "aliases": ["返航点"],
                    "map_id": "sentinel_map",
                    "pose": {"x": 1.0, "y": 2.0, "yaw": 0.3},
                }
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        waypoint = WaypointRegistry(path).require_navigation_target("home")
        self.assertTrue(waypoint.configured)
        self.assertEqual(waypoint.pose.x, 1.0)

        path.write_text(
            json.dumps([
                {
                    "waypoint_id": "wp_array",
                    "name": "数组点位",
                    "aliases": ["数组点"],
                    "map_id": "sentinel_map",
                    "pose": [3.0, 4.0, 1.57],
                }
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        array_waypoint = WaypointRegistry(path).require_navigation_target("wp_array")
        self.assertTrue(array_waypoint.configured)
        self.assertEqual(array_waypoint.pose.x, 3.0)
        self.assertEqual(array_waypoint.pose.yaw, 1.57)

        path.write_text(
            json.dumps([
                {"waypoint_id": "a", "name": "A", "aliases": ["同名"]},
                {"waypoint_id": "b", "name": "B", "aliases": ["同名"]},
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "别名冲突"):
            WaypointRegistry(path).list()

    async def test_real_mission_rejects_unconfigured_waypoint_before_executor(self) -> None:
        path = Path(self._temp_dir.name) / "waypoints_unconfigured.json"
        path.write_text(
            json.dumps([
                {
                    "waypoint_id": "wp_001",
                    "name": "一号点",
                    "aliases": ["一号"],
                    "map_id": "sentinel_map",
                    "pose": None,
                }
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        os.environ["WAYPOINTS_CONFIG_PATH"] = str(path)
        os.environ["NAV_MISSION_PREFLIGHT_ENABLED"] = "true"
        await main_module.switch_system_mode(ModeSwitchRequest(mode="real", source="test"))
        response = await main_module.go_to_waypoint(
            GoToWaypointRequest(waypoint_id="wp_001", source="test", requested_by="unittest")
        )
        self.assertFalse(response.data.accepted)
        self.assertIn("尚未配置地图坐标", response.data.detail)

    async def test_mission_update_is_persisted_and_deduplicated(self) -> None:
        await main_module.switch_system_mode(ModeSwitchRequest(mode="real", source="test"))
        timestamp = datetime.now(timezone.utc)
        event = TaskEvent(
            event_id="task-1:started:0",
            task_id="task-1",
            event_type="started",
            task_state="running",
            detail="已开始导航。",
            waypoint_id="wp_001",
            progress=5,
            timestamp=timestamp,
        )
        update = MissionExecutorUpdateRequest(
            event=event,
            task_status=TaskStatus(
                task_id="task-1",
                task_type="go_to_waypoint",
                state="running",
                progress=5,
                source="nav2_mission_executor",
                current_waypoint_id="wp_001",
                updated_at=timestamp,
            ),
            current_goal="wp_001",
            nav_state="running",
        )
        first = await main_module.ingest_mission_update(update)
        second = await main_module.ingest_mission_update(update)
        self.assertFalse(first.data.duplicate)
        self.assertTrue(second.data.duplicate)
        self.assertEqual(len(persistence.list_task_events()), 1)
        self.assertEqual(state_store.get_current_task().task_id, "task-1")

    def test_cboard_heartbeat_is_used_when_legacy_device_state_is_offline(self) -> None:
        heartbeat = Path(self._temp_dir.name) / "cboard.heartbeat"
        heartbeat.touch()
        os.environ["ROS2_IMU_HEARTBEAT_FILE"] = str(heartbeat)
        self.assertTrue(MissionGateway._cboard_heartbeat_fresh())

        old_timestamp = datetime.now(timezone.utc).timestamp() - 10
        os.utime(heartbeat, (old_timestamp, old_timestamp))
        self.assertFalse(MissionGateway._cboard_heartbeat_fresh())

    @staticmethod
    def _restore(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
