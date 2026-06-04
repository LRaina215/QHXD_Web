from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_INTENTS = {
    "go_to_waypoint",
    "start_patrol",
    "pause_task",
    "resume_task",
    "return_home",
    "query_status",
    "query_task",
    "query_detection",
    "query_self_identity",
    "query_capability",
    "query_safety_rule",
    "query_assistant_model",
    "query_robot_status",
    "query_task_status",
    "query_battery",
    "query_emergency_stop",
    "query_perception_status",
    "query_weather",
    "query_environment",
    "speak_last_result",
    "open_chat",
    "unknown",
}

ALLOWED_COMMANDS = {
    "go_to_waypoint",
    "start_patrol",
    "pause_task",
    "resume_task",
    "return_home",
    "query_status",
    "query_task",
    "query_detection",
    "query_self_identity",
    "query_capability",
    "query_safety_rule",
    "query_assistant_model",
    "query_robot_status",
    "query_task_status",
    "query_battery",
    "query_emergency_stop",
    "query_perception_status",
    "query_weather",
    "query_environment",
    "speak_last_result",
    "open_chat",
}

MOTION_COMMANDS = {"go_to_waypoint", "start_patrol", "return_home"}
LOW_RISK_COMMANDS = {
    "pause_task",
    "resume_task",
    "query_status",
    "query_task",
    "query_detection",
    "query_self_identity",
    "query_capability",
    "query_safety_rule",
    "query_assistant_model",
    "query_robot_status",
    "query_task_status",
    "query_battery",
    "query_emergency_stop",
    "query_perception_status",
    "query_weather",
    "query_environment",
    "speak_last_result",
    "open_chat",
}


@dataclass(frozen=True)
class LLMIntent:
    intent: str = "unknown"
    command: str | None = None
    waypoint_alias: str | None = None
    waypoint_id: str | None = None
    confidence: float = 0.0
    need_confirm: bool = True
    reason: str = ""
    reply_text: str | None = None
    missing_slots: list[str] = field(default_factory=list)
    ask_text: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMIntent":
        confidence = data.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        confidence_value = max(0.0, min(1.0, confidence_value))
        missing_slots = data.get("missing_slots", [])
        if not isinstance(missing_slots, list):
            missing_slots = []
        return cls(
            intent=str(data.get("intent") or "unknown"),
            command=str(data["command"]) if data.get("command") is not None else None,
            waypoint_alias=str(data["waypoint_alias"]) if data.get("waypoint_alias") is not None else None,
            waypoint_id=str(data["waypoint_id"]) if data.get("waypoint_id") is not None else None,
            confidence=confidence_value,
            need_confirm=bool(data.get("need_confirm", True)),
            reason=str(data.get("reason") or ""),
            reply_text=str(data["reply_text"]) if data.get("reply_text") is not None else None,
            missing_slots=[str(item) for item in missing_slots],
            ask_text=str(data["ask_text"]) if data.get("ask_text") is not None else None,
        )
