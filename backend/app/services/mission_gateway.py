from app.schemas import (
    GoToWaypointRequest,
    JsonScalar,
    MissionActionResult,
    MissionRequestBase,
    PauseMissionRequest,
    ResumeMissionRequest,
    ReturnHomeRequest,
    RobotState,
    StartPatrolRequest,
)
from app.services.mock_state import mock_state_service
from app.services.nav2_mission_adapter import nav2_mission_adapter
from app.services.navigation_store import navigation_store
from app.services.patrol_registry import patrol_registry
from app.services.persistence import persistence
from app.services.state_store import state_store
from app.services.waypoint_registry import waypoint_registry
from datetime import datetime, timezone
import os
from pathlib import Path


class MissionGateway:
    """Routes mission commands to mock simulation or the real task execution link."""

    def go_to_waypoint(self, request: GoToWaypointRequest) -> tuple[MissionActionResult, RobotState | None]:
        if state_store.get_system_mode().mode == "real" and self._preflight_enabled():
            rejected = self._preflight_target("go_to_waypoint", request.waypoint_id)
            if rejected is not None:
                return self._record_rejection(request, "go_to_waypoint", {"waypoint_id": request.waypoint_id}, rejected)
        return self._dispatch(
            request=request,
            public_command="go_to_waypoint",
            nuc_command="go_to_waypoint",
            payload={"waypoint_id": request.waypoint_id},
            mock_handler=mock_state_service.go_to_waypoint,
        )

    def start_patrol(self, request: StartPatrolRequest) -> tuple[MissionActionResult, RobotState | None]:
        if state_store.get_system_mode().mode == "real" and self._preflight_enabled():
            try:
                patrol_registry.require(request.patrol_id)
                self._require_navigation_ready()
            except ValueError as exc:
                return self._record_rejection(request, "start_patrol", {"patrol_id": request.patrol_id}, str(exc))
        return self._dispatch(
            request=request,
            public_command="start_patrol",
            nuc_command="start_patrol",
            payload={"patrol_id": request.patrol_id},
            mock_handler=mock_state_service.start_patrol,
        )

    def pause(self, request: PauseMissionRequest) -> tuple[MissionActionResult, RobotState | None]:
        return self._dispatch(
            request=request,
            public_command="pause",
            nuc_command="pause_task",
            payload={},
            mock_handler=mock_state_service.pause,
        )

    def resume(self, request: ResumeMissionRequest) -> tuple[MissionActionResult, RobotState | None]:
        if state_store.get_system_mode().mode == "real" and self._preflight_enabled():
            try:
                self._require_navigation_ready()
            except ValueError as exc:
                return self._record_rejection(request, "resume", {}, str(exc))
        return self._dispatch(
            request=request,
            public_command="resume",
            nuc_command="resume_task",
            payload={},
            mock_handler=mock_state_service.resume,
        )

    def return_home(self, request: ReturnHomeRequest) -> tuple[MissionActionResult, RobotState | None]:
        if state_store.get_system_mode().mode == "real" and self._preflight_enabled():
            rejected = self._preflight_target("return_home", "home")
            if rejected is not None:
                return self._record_rejection(request, "return_home", {}, rejected)
        return self._dispatch(
            request=request,
            public_command="return_home",
            nuc_command="return_home",
            payload={},
            mock_handler=mock_state_service.return_home,
        )

    def cancel(self, request: MissionRequestBase) -> tuple[MissionActionResult, RobotState | None]:
        if state_store.get_system_mode().mode == "mock":
            latest = state_store.get_latest_state()
            current = latest.task_status.model_copy(
                update={
                    "state": "cancelled", "progress": 0, "detail": "模拟任务已取消。",
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            result = MissionActionResult(
                accepted=True,
                command="cancel",
                task_status=current,
                received_at=datetime.now(timezone.utc),
                detail="模拟任务已取消。",
            )
            next_state = latest.model_copy(
                update={
                    "task_status": current,
                    "nav_status": latest.nav_status.model_copy(
                        update={"state": "idle", "current_goal": None, "remaining_distance": None}
                    ),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            published = state_store.publish_mock_state(next_state)
            persistence.save_command_log("cancel", request.source, request.requested_by, {}, result)
            return result, published
        return self._dispatch(
            request=request,
            public_command="cancel",
            nuc_command="cancel_task",
            payload={},
            mock_handler=lambda _: None,
        )

    def _dispatch(
        self,
        request: MissionRequestBase,
        public_command: str,
        nuc_command: str,
        payload: dict[str, JsonScalar],
        mock_handler,
    ) -> tuple[MissionActionResult, RobotState | None]:
        if state_store.get_system_mode().mode == "mock":
            result = mock_handler(request)
            state = state_store.publish_mock_state(mock_state_service.get_latest_state())
            return result, state

        result, state = nav2_mission_adapter.forward(
            command=nuc_command,
            source=request.source,
            requested_by=request.requested_by,
            payload=payload,
        )
        persistence.save_command_log(
            command=public_command,
            source=request.source,
            requested_by=request.requested_by,
            payload={**payload, "forwarded_command": nuc_command},
            result=result,
        )
        return result, state

    def _preflight_target(self, command: str, waypoint_id: str) -> str | None:
        try:
            waypoint = waypoint_registry.require_navigation_target(waypoint_id)
            self._require_navigation_ready(expected_map_id=waypoint.map_id)
        except ValueError as exc:
            return str(exc)
        return None

    def _require_navigation_ready(self, expected_map_id: str | None = None) -> None:
        state = state_store.get_latest_state()
        if state.device_status.emergency_stop:
            raise ValueError("急停已触发，禁止开始或恢复导航任务。")
        if not state.device_status.online and not self._cboard_heartbeat_fresh():
            raise ValueError("机器人真实状态离线且 C 板心跳过期，禁止开始或恢复导航任务。")
        blocking_faults = {"real-state-timeout", "real-command-link-unreachable", "emergency-stop"}
        if state.device_status.fault_code in blocking_faults:
            raise ValueError(f"机器人存在阻断故障：{state.device_status.fault_code}")

        metadata = navigation_store.map_metadata()
        snapshot = navigation_store.latest()
        if metadata is None:
            raise ValueError("导航地图尚未上传，禁止发送 Nav2 Goal。")
        if expected_map_id and metadata.map_id != expected_map_id:
            raise ValueError(f"点位地图 {expected_map_id} 与当前地图 {metadata.map_id} 不一致。")
        if snapshot is None or snapshot.pose is None:
            raise ValueError("导航定位尚未就绪，缺少 map 到 base_link 位姿。")
        age = (datetime.now(timezone.utc) - snapshot.timestamp).total_seconds()
        if age > self._max_navigation_age_seconds():
            raise ValueError(f"导航状态已过期 {age:.1f} 秒，禁止发送 Nav2 Goal。")

    def _record_rejection(
        self,
        request: MissionRequestBase,
        command: str,
        payload: dict[str, JsonScalar],
        detail: str,
    ) -> tuple[MissionActionResult, None]:
        result = MissionActionResult(
            accepted=False,
            command=command,
            task_status=state_store.get_current_task(),
            received_at=datetime.now(timezone.utc),
            detail=detail,
        )
        persistence.save_command_log(command, request.source, request.requested_by, payload, result)
        return result, None

    @staticmethod
    def _max_navigation_age_seconds() -> float:
        try:
            return max(1.0, float(os.getenv("NAV_MISSION_MAX_NAV_AGE_SECONDS", "3")))
        except ValueError:
            return 3.0

    @staticmethod
    def _cboard_heartbeat_fresh() -> bool:
        path = Path(
            os.getenv(
                "ROS2_IMU_HEARTBEAT_FILE",
                "/home/robomaster/QHXD/.runtime/ros2_imu_bridge.heartbeat",
            )
        )
        try:
            age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        except OSError:
            return False
        try:
            max_age = max(1.0, float(os.getenv("CBOARD_HEARTBEAT_MAX_AGE_SECONDS", "3")))
        except ValueError:
            max_age = 3.0
        return 0.0 <= age <= max_age

    @staticmethod
    def _preflight_enabled() -> bool:
        return os.getenv("NAV_MISSION_PREFLIGHT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


mission_gateway = MissionGateway()
