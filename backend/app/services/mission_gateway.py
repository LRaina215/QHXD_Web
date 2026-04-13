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
from app.services.nuc_adapter import nuc_adapter
from app.services.persistence import persistence
from app.services.state_store import state_store


class MissionGateway:
    """Routes mission commands to mock flow or NUC bridge based on current mode."""

    def go_to_waypoint(self, request: GoToWaypointRequest) -> tuple[MissionActionResult, RobotState | None]:
        return self._dispatch(
            request=request,
            public_command="go_to_waypoint",
            nuc_command="go_to_waypoint",
            payload={"waypoint_id": request.waypoint_id},
            mock_handler=mock_state_service.go_to_waypoint,
        )

    def start_patrol(self, request: StartPatrolRequest) -> tuple[MissionActionResult, RobotState | None]:
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
        return self._dispatch(
            request=request,
            public_command="resume",
            nuc_command="resume_task",
            payload={},
            mock_handler=mock_state_service.resume,
        )

    def return_home(self, request: ReturnHomeRequest) -> tuple[MissionActionResult, RobotState | None]:
        return self._dispatch(
            request=request,
            public_command="return_home",
            nuc_command="return_home",
            payload={},
            mock_handler=mock_state_service.return_home,
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

        result, state = nuc_adapter.forward_mission_command(
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


mission_gateway = MissionGateway()
