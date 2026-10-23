from __future__ import annotations

from dataclasses import dataclass, field
import os

from app.services.voice.llm_schema import ALLOWED_COMMANDS, ALLOWED_INTENTS, LOW_RISK_COMMANDS, MOTION_COMMANDS, LLMIntent
from app.services.waypoint_resolver import waypoint_resolver

SUPPORTED_TARGET_CLASSES = {"bottle", "cup", "person", "sports ball", "chair", "backpack"}
SUPPORTED_COLORS = {"red", "green", "blue", "yellow", "white", "black"}
_CLASS_ALIASES = {"水瓶": "bottle", "瓶子": "bottle", "杯子": "cup", "水杯": "cup", "人": "person", "行人": "person",
                  "球": "sports ball", "ball": "sports ball", "椅子": "chair", "背包": "backpack", "书包": "backpack"}
_COLOR_ALIASES = {"红": "red", "红色": "red", "绿": "green", "绿色": "green", "蓝": "blue", "蓝色": "blue",
                  "黄": "yellow", "黄色": "yellow", "白": "white", "白色": "white", "黑": "black", "黑色": "black"}
_CLASS_CN = {"bottle": "水瓶", "cup": "杯子", "person": "人", "sports ball": "球", "chair": "椅子", "backpack": "背包"}
_COLOR_CN = {"red": "红色", "green": "绿色", "blue": "蓝色", "yellow": "黄色", "white": "白色", "black": "黑色"}


def target_label(label: str | None, target_class: str, color: str | None) -> str:
    """界面与播报用的中文目标名：模型没给或给的是英文类别名时，用颜色 + 类别拼一个。"""
    text = (label or "").strip()
    if not text or normalize_class(text) == target_class or text.isascii():
        text = f"{_COLOR_CN.get(color or '', '')}{_CLASS_CN.get(target_class, target_class)}"
    return text[:32]


def normalize_class(value: str) -> str:
    key = (value or "").strip().lower()
    return _CLASS_ALIASES.get(key, key)


def normalize_color(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    return _COLOR_ALIASES.get(key, key)


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
            return self._reject(result, result.ask_text or result.reason or "抱歉，这句话我没听懂，请换种说法，或说具体任务（去 A 点、找红色水瓶、跟着我）。")
        if command not in ALLOWED_COMMANDS:
            return self._reject(result, "LLM 输出了不在白名单内的 command。")
        if result.confidence < _threshold():
            return self._reject(result, "抱歉，这句话我没听懂，请换种说法，或说具体任务（去 A 点、找红色水瓶、跟着我）。")
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
            payload["patrol_id"] = "default_patrol"
        elif command in {"search_target", "follow_target"}:
            target_class = normalize_class(result.target_class or ("person" if command == "follow_target" else ""))
            if target_class not in SUPPORTED_TARGET_CLASSES:
                return self._reject(result, f"目标类别「{result.target_class or '未指定'}」不在感知模型支持范围内，未触发任务。")
            color = normalize_color(result.target_color)
            if color is not None and color not in SUPPORTED_COLORS:
                return self._reject(result, f"目标颜色「{result.target_color}」无法识别，未触发任务。")
            payload["target_class"] = target_class
            if color:
                payload["color"] = color
            payload["label"] = target_label(result.target_label, target_class, color)

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
            detail=_task_detail(command, payload) or result.reply_text or result.reason
            or "LLM 语义解析通过本地安全校验。",
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


def _task_detail(command: str, payload: dict[str, str]) -> str | None:
    """任务类命令的回复按校验后的 payload 生成（与规则解析同样的说法），不用大模型自己写的 reply_text：
    小模型可能说错目标，而用户确认的应该是真正要执行的那个任务。"""
    if command == "pause_task":
        return "已解析为暂停当前任务。"
    if command == "resume_task":
        return "已解析为恢复当前任务。"
    if command == "go_to_waypoint":
        waypoint_id = payload.get("waypoint_id")
        name = next((str(item.get("name")) for item in waypoint_resolver.list_waypoints()
                     if item.get("waypoint_id") == waypoint_id and item.get("name")), waypoint_id)
        return f"已解析为前往{name}任务。"
    if command == "start_patrol":
        return "已解析为开始巡检任务。"
    if command == "return_home":
        return "已解析为返回起点任务。"
    if command == "search_target":
        return f"已解析为寻找「{payload.get('label') or payload.get('target_class')}」并移动到其附近的任务。"
    if command == "follow_target":
        return "已解析为跟随人员任务。" if payload.get("target_class") == "person"             else f"已解析为跟随「{payload.get('label') or payload.get('target_class')}」的任务。"
    return None
