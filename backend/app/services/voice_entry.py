from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from app.schemas import (
    GoToWaypointRequest,
    PauseMissionRequest,
    ResumeMissionRequest,
    ReturnHomeRequest,
    RobotState,
    StartPatrolRequest,
    VoiceCommandResult,
    VoiceConfirmCommandRequest,
    VoiceTextCommandRequest,
)
from app.services.intent_parser import ParsedIntent
from app.services.mission_gateway import mission_gateway
from app.services.state_store import state_store
from app.services.voice.llm_intent_parser import llm_intent_parser


MOTION_INTENTS = {"go_to_waypoint", "start_patrol", "return_home"}
QUERY_INTENTS = {"query_status", "query_task", "query_detection"}


@dataclass(frozen=True)
class PendingVoiceCommand:
    pending_command_id: str
    parsed: ParsedIntent
    request: VoiceTextCommandRequest
    expires_at: datetime


class VoiceEntryService:
    """Text-command entry point that reuses the existing mission gateway."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingVoiceCommand] = {}

    def handle_text_command(self, request: VoiceTextCommandRequest) -> tuple[VoiceCommandResult, RobotState | None]:
        parsed = llm_intent_parser.parse(request.text, use_llm=request.use_llm)

        if parsed.intent is None or parsed.intent == "unknown":
            return self._result(False, parsed, None, parsed.detail), None

        if parsed.intent in QUERY_INTENTS:
            return self._handle_query(parsed), None

        if parsed.need_confirm:
            if parsed.intent in MOTION_INTENTS and self._has_required_payload(parsed):
                pending_id = self._create_pending(parsed, request)
                detail = f"{parsed.detail} 请确认是否执行。"
                return self._result(False, parsed, parsed.intent, detail, pending_command_id=pending_id), None
            return self._result(False, parsed, parsed.intent, parsed.detail), None

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
                parser=parsed.parser,
                llm_backend=parsed.llm_backend,
                llm_model=parsed.llm_model,
                llm_raw_output=parsed.llm_raw_output,
            ),
            latest_state,
        )

    def confirm_pending_command(self, request: VoiceConfirmCommandRequest) -> tuple[VoiceCommandResult, RobotState | None]:
        self._purge_expired()
        pending = self._pending.pop(request.pending_command_id, None)
        if pending is None:
            parsed = ParsedIntent(intent=None, detail="待确认命令不存在或已过期，未触发任务。", parser="confirm")
            return self._result(False, parsed, None, parsed.detail), None
        if not request.confirmed:
            parsed = pending.parsed
            return self._result(
                False,
                parsed,
                parsed.intent,
                "已取消待确认语音命令，未触发任务。",
                pending_command_id=request.pending_command_id,
            ), None

        original = pending.request
        dispatch_request = VoiceTextCommandRequest(
            text=original.text,
            source=original.source or "voice-confirmed",
            requested_by=request.requested_by or original.requested_by,
            use_llm=False,
        )
        mission_result, latest_state = self._dispatch_mission(pending.parsed.intent, pending.parsed.payload, dispatch_request)
        return (
            VoiceCommandResult(
                accepted=mission_result.accepted if mission_result is not None else False,
                intent=pending.parsed.intent,
                command=pending.parsed.intent,
                payload=pending.parsed.payload,
                confidence=pending.parsed.confidence,
                need_confirm=False,
                detail=mission_result.detail if mission_result is not None else "确认命令执行失败。",
                task_status=mission_result.task_status if mission_result is not None else None,
                parser=pending.parsed.parser,
                llm_backend=pending.parsed.llm_backend,
                llm_model=pending.parsed.llm_model,
                llm_raw_output=pending.parsed.llm_raw_output,
                pending_command_id=request.pending_command_id,
            ),
            latest_state,
        )

    def _handle_query(self, parsed: ParsedIntent) -> VoiceCommandResult:
        latest_state = state_store.get_latest_state()
        if parsed.intent == "query_detection":
            detection = latest_state.detection_status
            if detection is None:
                detail = "当前没有视觉检测状态。"
            else:
                objects = ", ".join(f"{obj.class_name}:{obj.confidence:.2f}" for obj in detection.objects[:5]) or "无目标"
                detail = f"视觉检测来源 {detection.source}，最近目标：{objects}。"
        elif parsed.intent == "query_task":
            task = latest_state.task_status
            detail = f"当前任务 {task.task_type}/{task.state}，进度 {task.progress}%。"
        else:
            detail = (
                f"当前模式 {latest_state.system_mode.mode}，"
                f"任务 {latest_state.task_status.task_type}/{latest_state.task_status.state}，"
                f"目标 {latest_state.nav_status.current_goal or '未设置'}。"
            )
        return self._result(True, parsed, parsed.intent, detail, latest_state)

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

    def _create_pending(self, parsed: ParsedIntent, request: VoiceTextCommandRequest) -> str:
        self._purge_expired()
        pending_id = f"voice_pending_{uuid4().hex[:12]}"
        self._pending[pending_id] = PendingVoiceCommand(
            pending_command_id=pending_id,
            parsed=parsed,
            request=request,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._pending_ttl_seconds()),
        )
        return pending_id

    def _purge_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, value in self._pending.items() if value.expires_at <= now]
        for key in expired:
            self._pending.pop(key, None)

    @staticmethod
    def _pending_ttl_seconds() -> float:
        try:
            return max(1.0, float(os.getenv("VOICE_PENDING_TTL_SECONDS", "30")))
        except ValueError:
            return 30.0

    @staticmethod
    def _has_required_payload(parsed: ParsedIntent) -> bool:
        if parsed.intent == "go_to_waypoint":
            return bool(parsed.payload.get("waypoint_id"))
        if parsed.intent == "start_patrol":
            return True
        if parsed.intent == "return_home":
            return True
        return False

    @staticmethod
    def _result(
        accepted: bool,
        parsed: ParsedIntent,
        command: str | None,
        detail: str,
        latest_state: RobotState | None = None,
        pending_command_id: str | None = None,
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
            parser=parsed.parser,
            llm_backend=parsed.llm_backend,
            llm_model=parsed.llm_model,
            llm_raw_output=parsed.llm_raw_output,
            pending_command_id=pending_command_id,
        )


voice_entry_service = VoiceEntryService()
