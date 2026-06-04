import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas import MissionCandidate, SmartCommandRequest, SmartCommandResult, TTSStatus
from app.services.data_service import data_service
from app.services.voice.llm_intent_parser import llm_intent_parser
from app.services.tts_service import tts_service
from app.services.voice_entry import MOTION_INTENTS, QUERY_INTENTS, voice_entry_service


class SmartVoiceService:
    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path or Path(__file__).resolve().parents[2] / "data" / "smart_voice_logs.jsonl"

    def handle(self, request: SmartCommandRequest) -> tuple[SmartCommandResult, object | None]:
        request_id = f"smart_{uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc)
        text = request.text.strip()

        if not text:
            result = SmartCommandResult(
                request_id=request_id,
                recognized_text=request.text,
                intent=None,
                data_source="none",
                reply_text="我没有听到有效内容，请再说一次。",
                need_confirm=False,
                error_reason="empty_text",
                timestamp=timestamp,
            )
            self._log(result)
            return result, None

        parsed = llm_intent_parser.parse(text, use_llm=request.use_llm)

        if parsed.intent in QUERY_INTENTS:
            data_source, reply_text = data_service.reply_for_query(parsed.intent)
            result = SmartCommandResult(
                request_id=request_id,
                recognized_text=text,
                intent=parsed.intent,
                data_source=data_source,
                reply_text=reply_text,
                need_confirm=False,
                confidence=parsed.confidence,
                parser=parsed.parser,
                llm_backend=parsed.llm_backend,
                llm_model=parsed.llm_model,
                timestamp=timestamp,
            )
            result = self._with_tts(result, request.generate_tts)
            self._log(result)
            return result, None

        voice_result, state = voice_entry_service.handle_text_command(
            request.model_copy(update={"source": request.source or "smart-command"})
        )

        mission_candidate = None
        if voice_result.intent in MOTION_INTENTS or voice_result.command in {"pause_task", "resume_task"}:
            if voice_result.payload or voice_result.intent in {"start_patrol", "return_home", "pause_task", "resume_task"}:
                mission_candidate = MissionCandidate(
                    command=voice_result.intent,
                    payload=voice_result.payload,
                    pending_command_id=voice_result.pending_command_id,
                    detail=voice_result.detail,
                )

        error_reason = None
        if voice_result.intent in {None, "unknown"} or (voice_result.need_confirm and mission_candidate is None):
            error_reason = voice_result.detail

        reply_text = voice_result.detail
        if voice_result.need_confirm and mission_candidate is not None:
            reply_text = f"{voice_result.detail} 请在界面上确认或取消。"

        result = SmartCommandResult(
            request_id=request_id,
            recognized_text=text,
            intent=voice_result.intent,
            data_source="voice_parser",
            reply_text=reply_text,
            need_confirm=voice_result.need_confirm,
            mission_candidate=mission_candidate,
            pending_command_id=voice_result.pending_command_id,
            error_reason=error_reason,
            confidence=voice_result.confidence,
            parser=voice_result.parser,
            llm_backend=voice_result.llm_backend,
            llm_model=voice_result.llm_model,
            timestamp=timestamp,
        )
        result = self._with_tts(result, request.generate_tts)
        self._log(result)
        return result, state

    def _with_tts(self, result: SmartCommandResult, generate_tts: bool) -> SmartCommandResult:
        if not generate_tts or not result.reply_text:
            return result
        try:
            status = tts_service.speak(result.reply_text)
        except Exception as exc:
            status = TTSStatus(
                backend="unknown",
                status="failed",
                text=result.reply_text,
                detail=f"TTS 失败：{type(exc).__name__}",
                updated_at=datetime.now(timezone.utc),
            )
        return result.model_copy(update={"tts_status": status})

    def _log(self, result: SmartCommandResult) -> None:
        payload = {
            "request_id": result.request_id,
            "recognized_text": result.recognized_text,
            "intent": result.intent,
            "data_source": result.data_source,
            "reply_text": result.reply_text,
            "need_confirm": result.need_confirm,
            "mission_candidate": result.mission_candidate.model_dump(mode="json") if result.mission_candidate else None,
            "tts_status": result.tts_status.model_dump(mode="json") if result.tts_status else None,
            "error_reason": result.error_reason,
            "timestamp": result.timestamp.isoformat(),
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception:
            pass


smart_voice_service = SmartVoiceService()
