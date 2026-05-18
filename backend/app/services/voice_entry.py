from app.schemas import (
    GoToWaypointRequest,
    PauseMissionRequest,
    ResumeMissionRequest,
    ReturnHomeRequest,
    RobotState,
    StartPatrolRequest,
    VoiceCommandResult,
    VoiceTextCommandRequest,
)
from app.services.intent_parser import intent_parser
from app.services.mission_gateway import mission_gateway
from app.services.state_store import state_store


class VoiceEntryService:
    """Text-command entry point that reuses the existing mission gateway."""

    def handle_text_command(self, request: VoiceTextCommandRequest) -> tuple[VoiceCommandResult, RobotState | None]:
        parsed = intent_parser.parse(request.text)

        if parsed.intent is None:
            return self._result(False, parsed, None, parsed.detail), None

        if parsed.need_confirm:
            return self._result(False, parsed, parsed.intent, parsed.detail), None

        if parsed.intent == "query_status":
            latest_state = state_store.get_latest_state()
            detail = (
                f"当前模式 {latest_state.system_mode.mode}，"
                f"任务 {latest_state.task_status.task_type}/{latest_state.task_status.state}，"
                f"目标 {latest_state.nav_status.current_goal or '未设置'}。"
            )
            return self._result(True, parsed, "query_status", detail, latest_state), None

        mission_result, latest_state = self._dispatch_mission(parsed.intent, parsed.payload, request)
        detail = mission_result.detail if mission_result is not None else parsed.detail
        return (
            VoiceCommandResult(
                accepted=mission_result.accepted if mission_result is not None else False,
                intent=parsed.intent,
                command=parsed.intent,
                payload=parsed.payload,
                confidence=parsed.confidence,
                need_confirm=False,
                detail=detail,
                task_status=mission_result.task_status if mission_result is not None else None,
            ),
            latest_state,
        )

    def _dispatch_mission(self, intent: str, payload: dict, request: VoiceTextCommandRequest):
        source = request.source or "voice-text"
        if intent == "go_to_waypoint":
            return mission_gateway.go_to_waypoint(
                GoToWaypointRequest(
                    waypoint_id=str(payload["waypoint_id"]),
                    source=source,
                    requested_by=request.requested_by,
                )
            )
        if intent == "start_patrol":
            return mission_gateway.start_patrol(
                StartPatrolRequest(
                    patrol_id=str(payload.get("patrol_id", "patrol_default")),
                    source=source,
                    requested_by=request.requested_by,
                )
            )
        if intent == "pause_task":
            return mission_gateway.pause(PauseMissionRequest(source=source, requested_by=request.requested_by))
        if intent == "resume_task":
            return mission_gateway.resume(ResumeMissionRequest(source=source, requested_by=request.requested_by))
        if intent == "return_home":
            return mission_gateway.return_home(ReturnHomeRequest(source=source, requested_by=request.requested_by))
        raise ValueError(f"Unsupported voice mission intent: {intent}")

    @staticmethod
    def _result(
        accepted: bool,
        parsed,
        command: str | None,
        detail: str,
        latest_state: RobotState | None = None,
    ) -> VoiceCommandResult:
        return VoiceCommandResult(
            accepted=accepted,
            intent=parsed.intent,
            command=command,
            payload=parsed.payload,
            confidence=parsed.confidence,
            need_confirm=parsed.need_confirm,
            detail=detail,
            task_status=latest_state.task_status if latest_state is not None else None,
        )


voice_entry_service = VoiceEntryService()
