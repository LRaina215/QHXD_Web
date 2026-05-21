from dataclasses import dataclass, field

from app.schemas import JsonScalar, VoiceIntentValue
from app.services.waypoint_resolver import waypoint_resolver


@dataclass(frozen=True)
class ParsedIntent:
    intent: VoiceIntentValue | None
    payload: dict[str, JsonScalar] = field(default_factory=dict)
    confidence: float = 0.0
    need_confirm: bool = True
    detail: str = "未识别到可执行任务。"


class IntentParser:
    """Small rule-based parser for Phase 4A text command debugging."""

    def parse(self, text: str) -> ParsedIntent:
        normalized = self._normalize(text)
        if not normalized:
            return ParsedIntent(intent=None, detail="文本命令为空，未触发任务。")

        if self._contains_any(normalized, ["当前状态", "现在在哪", "现在位置", "在哪", "状态"]):
            return ParsedIntent(
                intent="query_status",
                confidence=0.92,
                need_confirm=False,
                detail="已解析为状态查询。",
            )

        if self._contains_any(normalized, ["暂停任务", "暂停", "停一下"]):
            return ParsedIntent(
                intent="pause_task",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为暂停当前任务。",
            )

        if self._contains_any(normalized, ["继续任务", "恢复任务", "继续", "恢复"]):
            return ParsedIntent(
                intent="resume_task",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为恢复当前任务。",
            )

        if self._contains_any(normalized, ["返回起点", "回到起点", "返航", "回家", "返回home", "返回洗脸"]):
            return ParsedIntent(
                intent="return_home",
                confidence=0.95,
                need_confirm=False,
                detail="已解析为返回起点任务。",
            )

        if self._contains_any(normalized, ["开始巡检", "开始巡视", "巡检", "巡视"]):
            return ParsedIntent(
                intent="start_patrol",
                payload={"patrol_id": "patrol_default"},
                confidence=0.9,
                need_confirm=False,
                detail="已解析为开始巡检任务。",
            )

        if self._contains_any(normalized, ["去", "到", "前往", "送到"]):
            waypoint = waypoint_resolver.resolve_detail(text)
            if waypoint.ambiguous:
                names = "、".join(f"{item['name']}({item['waypoint_id']})" for item in waypoint.matches)
                return ParsedIntent(
                    intent="go_to_waypoint",
                    confidence=0.4,
                    need_confirm=True,
                    detail=f"目标点存在歧义：{names}，未触发任务。",
                )
            if waypoint.waypoint_id is not None:
                return ParsedIntent(
                    intent="go_to_waypoint",
                    payload={"waypoint_id": waypoint.waypoint_id},
                    confidence=0.95,
                    need_confirm=False,
                    detail=f"已解析为前往{waypoint.name or waypoint.waypoint_id}任务。",
                )
            return ParsedIntent(
                intent="go_to_waypoint",
                confidence=0.42,
                need_confirm=True,
                detail="识别到前往目标点意图，但没有匹配到已配置目标点，未触发任务。",
            )

        return ParsedIntent(
            intent=None,
            confidence=0.0,
            need_confirm=True,
            detail="未知文本命令，未触发机器人任务。",
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(value.lower().split())

    @staticmethod
    def _contains_any(value: str, keywords: list[str]) -> bool:
        return any(keyword in value for keyword in keywords)


intent_parser = IntentParser()
