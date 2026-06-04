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
    parser: str = "rule"
    llm_backend: str | None = None
    llm_model: str | None = None
    llm_raw_output: str | None = None


class IntentParser:
    """Small rule-based parser for Phase 4A text command debugging."""

    def parse(self, text: str) -> ParsedIntent:
        normalized = self._normalize(text)
        if not normalized:
            return ParsedIntent(intent=None, detail="文本命令为空，未触发任务。")

        if self._contains_any(normalized, ["使用的模型", "用的模型", "什么模型", "大模型", "deepseek", "llm模型"]):
            return ParsedIntent(
                intent="query_assistant_model",
                confidence=0.97,
                need_confirm=False,
                detail="已解析为智能助手模型查询。",
            )

        if self._contains_any(normalized, ["你是谁", "你叫什么名字", "叫什么", "自我介绍", "介绍一下自己"]):
            return ParsedIntent(
                intent="query_self_identity",
                confidence=0.98,
                need_confirm=False,
                detail="已解析为身份查询。",
            )

        if self._contains_any(normalized, ["你能做什么", "你会做什么", "有什么能力", "你的能力", "可以做什么"]):
            return ParsedIntent(
                intent="query_capability",
                confidence=0.97,
                need_confirm=False,
                detail="已解析为能力查询。",
            )

        if self._contains_any(normalized, ["安全规则", "安全边界", "自己控制底盘", "直接控制底盘", "控制底盘吗"]):
            return ParsedIntent(
                intent="query_safety_rule",
                confidence=0.97,
                need_confirm=False,
                detail="已解析为安全规则查询。",
            )

        if self._contains_any(normalized, ["向前走", "往前走", "开快", "快一点", "走一米", "撞过去", "速度", "底盘速度"]):
            return ParsedIntent(
                intent="unknown",
                confidence=0.95,
                need_confirm=True,
                detail="拒绝直接速度控制或危险运动请求，未触发任务。",
            )

        if self._contains_any(normalized, ["天气", "下雨", "温度", "湿度", "环境适合", "适合巡检"]):
            return ParsedIntent(
                intent="query_weather",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为天气/环境查询。",
            )

        if self._contains_any(normalized, ["视觉检测", "看到了什么", "检测到了什么", "识别到了什么", "刚才看到了"]):
            return ParsedIntent(
                intent="query_perception_status",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为视觉状态查询。",
            )

        if self._contains_any(normalized, ["当前任务", "任务是什么", "任务状态", "任务进度"]):
            return ParsedIntent(
                intent="query_task_status",
                confidence=0.93,
                need_confirm=False,
                detail="已解析为任务状态查询。",
            )

        if self._contains_any(normalized, ["多少电", "电量", "还有电"]):
            return ParsedIntent(
                intent="query_battery",
                confidence=0.93,
                need_confirm=False,
                detail="已解析为电量查询。",
            )

        if self._contains_any(normalized, ["急停", "有没有急停"]):
            return ParsedIntent(
                intent="query_emergency_stop",
                confidence=0.93,
                need_confirm=False,
                detail="已解析为急停状态查询。",
            )

        if self._contains_any(normalized, ["当前状态", "现在在哪", "现在位置", "在哪", "状态", "正常吗"]):
            return ParsedIntent(
                intent="query_robot_status",
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
                need_confirm=True,
                detail="已解析为返回起点任务。",
            )

        if self._contains_any(normalized, ["开始巡检", "开始巡视", "巡检", "巡视"]):
            return ParsedIntent(
                intent="start_patrol",
                payload={"patrol_id": "patrol_default"},
                confidence=0.9,
                need_confirm=True,
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
                    need_confirm=True,
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
