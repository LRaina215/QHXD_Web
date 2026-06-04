from __future__ import annotations

from dataclasses import dataclass, field
import os

from app.services.voice.llm_schema import ALLOWED_COMMANDS, ALLOWED_INTENTS, LOW_RISK_COMMANDS, MOTION_COMMANDS, LLMIntent
from app.services.waypoint_resolver import waypoint_resolver


@dataclass(frozen=True)
class SafeLLMIntent:
    ok: bool
    intent: str = "unknown"
    command: str | None = None
    payload: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    need_confirm: bool = True
    detail: str = "LLM 输出未通过安全校验。"


def _threshold() -> float:
    try:
        return float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.75"))
    except ValueError:
        return 0.75


def _require_confirm_for_motion() -> bool:
    value = os.getenv("LLM_REQUIRE_CONFIRM_FOR_MOTION", "true")
    return value.strip().lower() in {"1", "true", "yes", "on"}


class LLMSafetyValidator:
    def validate(self, result: LLMIntent) -> SafeLLMIntent:
        intent = result.intent
        command = result.command or (intent if intent in ALLOWED_COMMANDS else None)
        if intent not in ALLOWED_INTENTS:
            return self._reject(result, "LLM 输出了不在白名单内的 intent。")
        if intent == "unknown":
            return self._reject(result, result.ask_text or result.reason or "LLM 无法确定机器人任务。")
        if command not in ALLOWED_COMMANDS:
            return self._reject(result, "LLM 输出了不在白名单内的 command。")
        if result.confidence < _threshold():
            return self._reject(result, f"LLM 置信度 {result.confidence:.2f} 低于阈值。")
        if result.missing_slots:
            return self._reject(result, result.ask_text or f"缺少必要槽位：{', '.join(result.missing_slots)}。")
        if command == "open_chat":
            reply_text = (result.reply_text or result.reason or "").strip()
            if not reply_text:
                return self._reject(result, "LLM 开放回答缺少 reply_text，未触发任务。")
            return SafeLLMIntent(
                ok=True,
                intent="open_chat",
                command="open_chat",
                payload={},
                confidence=result.confidence,
                need_confirm=False,
                detail=reply_text,
            )

        payload: dict[str, str] = {}
        if command == "go_to_waypoint":
            waypoint_id = result.waypoint_id
            if not waypoint_resolver.waypoint_exists(waypoint_id):
                if result.waypoint_alias:
                    resolved = waypoint_resolver.resolve_detail(result.waypoint_alias)
                    if not resolved.ambiguous and resolved.waypoint_id is not None:
                        waypoint_id = resolved.waypoint_id
                if not waypoint_resolver.waypoint_exists(waypoint_id):
                    return self._reject(result, "LLM 目标点不存在或未能唯一匹配，未触发任务。")
            payload["waypoint_id"] = str(waypoint_id)
        elif command == "start_patrol":
            payload["patrol_id"] = "patrol_default"

        need_confirm = bool(result.need_confirm)
        if command in MOTION_COMMANDS and _require_confirm_for_motion():
            need_confirm = True
        elif command in LOW_RISK_COMMANDS:
            need_confirm = False

        return SafeLLMIntent(
            ok=True,
            intent=intent,
            command=command,
            payload=payload,
            confidence=result.confidence,
            need_confirm=need_confirm,
            detail=result.reply_text or result.reason or "LLM 语义解析通过本地安全校验。",
        )

    @staticmethod
    def _reject(result: LLMIntent, detail: str) -> SafeLLMIntent:
        return SafeLLMIntent(
            ok=False,
            intent="unknown",
            command=None,
            confidence=max(0.0, min(1.0, result.confidence)),
            need_confirm=True,
            detail=detail,
        )


llm_safety_validator = LLMSafetyValidator()
