import json
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    PauseMissionRequest,
    RobotPose,
    ResumeMissionRequest,
    ReturnHomeRequest,
    TaskStatus,
)
from app.services.mock_state import MockStateService
from app.services.mode_manager import mode_manager
from app.services.persistence import persistence
from app.services.state_store import state_store


class _FakeNucMissionServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self._server.requests = []
        self._server.current_goal = None
        self._server.task_status = {
            "task_id": "nuc-task-idle",
            "task_type": "placeholder",
            "state": "idle",
            "progress": 0,
            "source": "nuc",
        }
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict]:
        return self._server.requests

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _build_handler(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/internal/rk3588/mission":
                    self.send_response(404)
                    self.end_headers()
                    return

                raw_length = self.headers.get("Content-Length", "0")
                request_length = int(raw_length)
                body = self.rfile.read(request_length)
                payload = json.loads(body.decode("utf-8"))
                self.server.requests.append(payload)

                command = payload["command"]
                command_payload = payload["payload"]
                current_goal = self.server.current_goal
                task_status = self.server.task_status.copy()
                nav_state = "idle"
                detail = f"NUC 已受理 {command} 命令。"

                if command == "go_to_waypoint":
                    current_goal = command_payload["waypoint_id"]
                    task_status = {
                        "task_id": "nuc-task-go-to-waypoint",
                        "task_type": "go_to_waypoint",
                        "state": "running",
                        "progress": 10,
                        "source": "nuc",
                    }
                    nav_state = "running"
                elif command == "start_patrol":
                    current_goal = command_payload["patrol_id"]
                    task_status = {
                        "task_id": "nuc-task-start-patrol",
                        "task_type": "start_patrol",
                        "state": "running",
                        "progress": 5,
                        "source": "nuc",
                    }
                    nav_state = "running"
                elif command == "pause_task":
                    task_status.update({"state": "paused", "source": "nuc"})
                    nav_state = "paused"
                elif command == "resume_task":
                    task_status.update({"state": "running", "source": "nuc"})
                    nav_state = "running"
                elif command == "return_home":
                    current_goal = "home"
                    task_status = {
                        "task_id": "nuc-task-return-home",
                        "task_type": "return_home",
                        "state": "running",
                        "progress": 15,
                        "source": "nuc",
                    }
                    nav_state = "running"
                else:
                    detail = f"未知命令 {command}"

                self.server.current_goal = current_goal
                self.server.task_status = task_status
                response_body = {
                    "success": True,
                    "data": {
                        "accepted": True,
                        "command": command,
                        "task_status": task_status,
                        "current_goal": current_goal,
                        "nav_state": nav_state,
                        "received_at": datetime.now(timezone.utc).isoformat(),
                        "detail": detail,
                    },
                }
                encoded = json.dumps(response_body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        return Handler


class Phase1BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = persistence._db_path
        self._original_service = main_module.mock_state_service
        self._original_nuc_base_url = os.environ.get("NUC_BASE_URL")
        self._original_nuc_mission_path = os.environ.get("NUC_MISSION_PATH")
        self._original_nuc_timeout = os.environ.get("NUC_TIMEOUT_SECONDS")
        self._original_real_stale_after = os.environ.get("REAL_STATE_STALE_AFTER_SECONDS")

        persistence._db_path = Path(self._temp_dir.name) / "phase1-test.db"
        main_module.mock_state_service = MockStateService()
        main_module.mock_state_service.initialize()
        state_store.initialize(main_module.mock_state_service.get_latest_state())
        mode_manager.initialize(state_store.get_latest_state())

    def tearDown(self) -> None:
        main_module.mock_state_service = self._original_service
        persistence._db_path = self._original_db_path
        self._restore_env("NUC_BASE_URL", self._original_nuc_base_url)
        self._restore_env("NUC_MISSION_PATH", self._original_nuc_mission_path)
        self._restore_env("NUC_TIMEOUT_SECONDS", self._original_nuc_timeout)
        self._restore_env("REAL_STATE_STALE_AFTER_SECONDS", self._original_real_stale_after)
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
        self.assertFalse(latest_state.device_status.online)
        self.assertEqual(latest_state.device_status.fault_code, "waiting-for-real-state")
        self.assertEqual(latest_state.nav_status.state, "offline")

    async def test_switching_back_to_mock_restores_mock_state_contract(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )

        response = await main_module.switch_system_mode(
            ModeSwitchRequest(mode="mock", source="test", requested_by="unittest")
        )
        latest_state = state_store.get_latest_state()

        self.assertTrue(response.success)
        self.assertEqual(response.data.system_mode.mode, "mock")
        self.assertEqual(latest_state.system_mode.mode, "mock")
        self.assertTrue(latest_state.device_status.online)
        self.assertEqual(latest_state.device_status.fault_code, None)
        self.assertEqual(latest_state.env_sensor.status, "mock")

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
        self.assertIn("alert-real-001", [alert.alert_id for alert in alerts])
        self.assertTrue(latest_state.device_status.online)

    async def test_real_mode_forwards_three_commands_to_nuc_and_persists_logs(self) -> None:
        server = _FakeNucMissionServer()
        server.start()
        os.environ["NUC_BASE_URL"] = server.base_url

        try:
            await main_module.switch_system_mode(
                ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
            )

            go_to_response = await main_module.go_to_waypoint(
                GoToWaypointRequest(
                    waypoint_id="wp-real-007",
                    source="test",
                    requested_by="unittest",
                )
            )
            pause_response = await main_module.pause_mission(
                PauseMissionRequest(source="test", requested_by="unittest")
            )
            return_home_response = await main_module.return_home(
                ReturnHomeRequest(source="test", requested_by="unittest")
            )
        finally:
            server.stop()

        latest_state = state_store.get_latest_state()
        logs = persistence.list_command_logs(limit=5)

        self.assertTrue(go_to_response.data.accepted)
        self.assertTrue(pause_response.data.accepted)
        self.assertTrue(return_home_response.data.accepted)
        self.assertEqual(
            [payload["command"] for payload in server.requests],
            ["go_to_waypoint", "pause_task", "return_home"],
        )
        self.assertEqual(len(logs), 3)
        self.assertEqual(logs[0].command, "return_home")
        self.assertEqual(logs[1].payload["forwarded_command"], "pause_task")
        self.assertEqual(latest_state.system_mode.mode, "real")
        self.assertEqual(latest_state.task_status.source, "nuc")
        self.assertEqual(latest_state.nav_status.current_goal, "home")

    async def test_real_mode_returns_structured_failure_when_nuc_unreachable(self) -> None:
        os.environ["NUC_BASE_URL"] = "http://127.0.0.1:1"
        os.environ["NUC_TIMEOUT_SECONDS"] = "0.2"

        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        response = await main_module.resume_mission(
            ResumeMissionRequest(source="test", requested_by="unittest")
        )
        logs = persistence.list_command_logs(limit=5)

        self.assertTrue(response.success)
        self.assertFalse(response.data.accepted)
        self.assertIn("NUC 命令接口", response.data.detail)
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].accepted)
        self.assertEqual(logs[0].command, "resume")
        self.assertFalse(state_store.get_latest_state().device_status.online)
        self.assertEqual(state_store.get_latest_state().device_status.fault_code, "nuc-bridge-unreachable")

    async def test_real_mode_timeout_marks_state_offline_and_recovery_restores_online(self) -> None:
        os.environ["REAL_STATE_STALE_AFTER_SECONDS"] = "0"

        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=1.0,
                    y=2.0,
                    yaw=0.3,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-timeout",
                    remaining_distance=1.2,
                ),
                task_status=TaskStatus(
                    task_id="task-timeout-001",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=50,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=80,
                    emergency_stop=False,
                    fault_code=None,
                    online=True,
                ),
                env_sensor=EnvSensor(
                    temperature_c=24.0,
                    humidity_percent=40.0,
                    status="nominal",
                ),
                alerts=[],
                updated_at=datetime.now(timezone.utc),
            )
        )

        timed_out_state = mode_manager.poll_real_health()

        self.assertIsNotNone(timed_out_state)
        self.assertFalse(timed_out_state.device_status.online)
        self.assertEqual(timed_out_state.device_status.fault_code, "nuc-state-timeout")
        self.assertEqual(timed_out_state.nav_status.state, "offline")

        await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=3.0,
                    y=4.0,
                    yaw=0.6,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-recovered",
                    remaining_distance=0.8,
                ),
                task_status=TaskStatus(
                    task_id="task-timeout-002",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=70,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=78,
                    emergency_stop=False,
                    fault_code=None,
                    online=True,
                ),
                env_sensor=EnvSensor(
                    temperature_c=25.0,
                    humidity_percent=41.0,
                    status="nominal",
                ),
                alerts=[],
                updated_at=datetime.now(timezone.utc),
            )
        )
        recovered_state = state_store.get_latest_state()

        self.assertTrue(recovered_state.device_status.online)
        self.assertEqual(recovered_state.nav_status.current_goal, "wp-recovered")
        self.assertEqual(recovered_state.device_status.fault_code, None)

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

    @staticmethod
    def _restore_env(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
