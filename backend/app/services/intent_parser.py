from dataclasses import dataclass, field

from app.schemas import JsonScalar, VoiceIntentValue
from app.services.waypoint_resolver import waypoint_resolver

FOLLOW_KEYWORDS = ["跟着我", "跟随我", "跟我走", "跟上我", "跟着他", "跟着她", "跟随人员", "跟随行人", "跟着人"]
SEARCH_KEYWORDS = ["找到", "寻找", "去找", "找一下", "找找", "找个", "找一个", "帮我找", "搜索", "找"]
# 长词在前，避免「水瓶」被「瓶」截胡；英文名与感知模型（COCO 标签）一致
TARGET_CLASS_WORDS = [
    ("矿泉水瓶", "bottle"), ("水瓶", "bottle"), ("瓶子", "bottle"), ("饮料", "bottle"), ("瓶", "bottle"),
    ("水杯", "cup"), ("杯子", "cup"), ("杯", "cup"),
    ("行人", "person"), ("人员", "person"), ("人", "person"),
    ("足球", "sports ball"), ("篮球", "sports ball"), ("球", "sports ball"),
    ("椅子", "chair"), ("背包", "backpack"), ("书包", "backpack"),
]
COLOR_WORDS = [("红", "red"), ("绿", "green"), ("蓝", "blue"), ("黄", "yellow"), ("白", "white"), ("黑", "black")]


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

    def __init__(self) -> None:
        self._last_query: tuple[str, float] | None = None      # (intent, monotonic) 最近一次查询意图，供追问用

    def parse(self, text: str) -> ParsedIntent:
        normalized = self._normalize(text)
        if not normalized:
            return ParsedIntent(intent=None, detail="我没听到内容，再说一遍要做什么。")

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

        if self._contains_any(normalized, ["向前走", "往前走", "开快", "快一点", "走一米", "撞过去", "速度", "底盘速度",
                                           "撞", "全速", "最快", "高速", "加速", "冲过去", "跑快",
                                           "关掉急停", "关闭急停", "关急停", "解除急停", "取消急停", "忽略"]):
            return ParsedIntent(
                intent="unknown",
                confidence=0.95,
                need_confirm=True,
                detail="这个我不能做，会撞到或者失控，换个安全的指令试试。",
            )

        if self._contains_any(normalized, ["关机", "重启", "删除", "格式化", "写代码", "写一段代码", "编程",
                                            "黑客", "病毒", "下载", "发邮件", "拍照", "录像", "播放音乐",
                                            "删文件", "删掉", "清除", "脚本", "命令行", "终端"]):
            return ParsedIntent(
                intent="unknown",
                confidence=0.95,
                need_confirm=False,
                detail="这类操作我支持不了。我可以导航、巡检、找东西、跟着你，或者问我的状态和天气。",
            )

        target_task = self._parse_target_task(normalized)
        if target_task is not None:
            return target_task

        if self._contains_any(normalized, ["你好", "早上好", "晚上好", "下午好", "哈喽", "嗨", "hi", "hello", "早安", "晚安", "在吗", "在不在"]):
            return ParsedIntent(
                intent="open_chat",
                confidence=0.9,
                need_confirm=False,
                detail="你好，我在，有什么可以帮你的？",
            )

        if self._contains_any(normalized, ["天气", "下雨", "温度", "湿度", "环境适合", "适合巡检", "冷吗", "热吗", "冷不冷", "热不热", "会下雨", "要不要带伞", "紫外线", "风大", "刮不刮风"]):
            return self._remember("query_weather", ParsedIntent(
                intent="query_weather",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为天气/环境查询。",
            ))

        follow_up = self._query_follow_up(normalized)
        if follow_up is not None:
            return follow_up

        if self._contains_any(normalized, ["当前导航", "导航状态", "导航怎么样", "导航正常", "还要走多远", "剩余距离"]):
            return self._remember("query_navigation_status", ParsedIntent(
                intent="query_navigation_status",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为导航状态查询。",
            ))

        if self._contains_any(normalized, ["前面有什么", "前方有什么", "前面有没有", "前方有没有", "前方状况", "前面状况", "前方情况", "前面情况"]):
            return ParsedIntent(
                intent="query_front_status",
                confidence=0.95,
                need_confirm=False,
                detail="已解析为导航前方态势查询。",
            )

        if self._contains_any(normalized, ["前方安全吗", "前面安全吗", "能不能继续走", "可以继续走吗", "前方安全", "前面安全"]):
            return ParsedIntent(
                intent="query_navigation_safety",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为前方安全态势查询。",
            )

        if self._contains_any(normalized, ["有没有障碍", "障碍物", "前方障碍", "前面障碍", "挡路"]):
            return ParsedIntent(
                intent="query_obstacle_status",
                confidence=0.94,
                need_confirm=False,
                detail="已解析为前方障碍查询。",
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

        if self._contains_any(normalized, ["取消任务", "停止任务", "终止任务", "别去了", "别走了", "不要去了", "停下任务"]):
            return ParsedIntent(
                intent="cancel_task",
                confidence=0.93,
                need_confirm=False,
                detail="已解析为取消当前任务。",
            )

        if self._contains_any(normalized, ["取消", "停止", "停下"]):
            return ParsedIntent(
                intent="cancel_task",
                confidence=0.88,
                need_confirm=False,
                detail="已解析为取消当前任务。",
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
                payload={"patrol_id": "default_patrol"},
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
                    detail=f"你说的这个点有好几个：{names}，说得更具体一点。",
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
                detail="你说的这个点我没有，能说个具体的点位吗？比如 A 点、B 点、C 点或起点。",
            )

        return ParsedIntent(
            intent=None,
            confidence=0.0,
            need_confirm=True,
            detail="未知文本命令，未触发机器人任务。",
        )

    def _remember(self, intent: str, parsed: ParsedIntent) -> ParsedIntent:
        import time as _time
        self._last_query = (intent, _time.monotonic())
        return parsed

    def _query_follow_up(self, normalized: str) -> ParsedIntent | None:
        """追问：上一轮问过天气，这轮只说"明天呢 / 后天冷不冷"这类短句时，按天气继续答。"""
        import time as _time
        if not self._last_query or _time.monotonic() - self._last_query[1] > 120:
            return None
        intent = self._last_query[0]
        if len(normalized) > 12 or not any(k in normalized for k in ("明天", "后天", "大后天", "周末", "今晚", "傍晚", "呢")):
            return None
        if any(k in normalized for k in ("去", "找", "跟", "暂停", "继续", "回", "巡", "停", "急停")):
            return None
        if intent == "query_weather":
            return ParsedIntent(
                intent="query_weather",
                confidence=0.85,
                need_confirm=False,
                detail="已解析为天气/环境查询。",
            )
        return None

    def _parse_target_task(self, normalized: str) -> ParsedIntent | None:
        """视觉目标任务：「找到红色水瓶并移动到其附近」「跟着我」。"""
        if self._contains_any(normalized, FOLLOW_KEYWORDS):
            return ParsedIntent(
                intent="follow_target",
                payload={"target_class": "person", "label": "我" if "我" in normalized else "人员"},
                confidence=0.93,
                need_confirm=True,
                detail="已解析为跟随人员任务。",
            )
        if not self._contains_any(normalized, SEARCH_KEYWORDS):
            return None
        target = next(((word, cls) for word, cls in TARGET_CLASS_WORDS if word in normalized), None)
        if target is None:
            return ParsedIntent(
                intent="search_target",
                confidence=0.4,
                need_confirm=True,
                detail="想找什么？我能找水瓶、杯子、人、球、椅子或背包。",
            )
        word, target_class = target
        color = next(((cn, en) for cn, en in COLOR_WORDS if cn in normalized), None)
        label = f"{color[0]}色{word}" if color else word
        payload: dict[str, JsonScalar] = {"target_class": target_class, "label": label}
        if color:
            payload["color"] = color[1]
        return ParsedIntent(
            intent="search_target",
            payload=payload,
            confidence=0.93,
            need_confirm=True,
            detail=f"已解析为寻找「{label}」并移动到其附近的任务。",
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(value.lower().split())

    @staticmethod
    def _contains_any(value: str, keywords: list[str]) -> bool:
        return any(keyword in value for keyword in keywords)


intent_parser = IntentParser()
