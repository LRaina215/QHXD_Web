from __future__ import annotations

import json
import os

from app.services.voice.llm_schema import ALLOWED_INTENTS
from app.services.waypoint_resolver import waypoint_resolver

SYSTEM_PROMPT = """你是云拓（多模态复杂地形轮腿机器人）的受控型智能语音助手。
你必须把用户文本解析为允许的 JSON 意图。
你不能直接控制机器人。
你可以在 reply_text 中输出自然语言回答，但最外层只能输出 JSON。
你不能编造 waypoint_id。
你不能生成代码、shell 命令或任意操作指令。
如果用户是开放问答且不涉及机器人控制，返回 intent=open_chat，并把回答写入 reply_text。
如果用户询问机器人本体状态、天气、视觉、身份、能力、安全规则或助手模型，返回对应 query intent，不要编造数据。
如果无法确定任务或请求危险控制，返回 intent=unknown。
只输出一个 JSON 对象，不要输出 Markdown。"""

JSON_SCHEMA = {
    "intent": "go_to_waypoint | start_patrol | pause_task | resume_task | return_home | search_target | follow_target | query_self_identity | query_capability | query_safety_rule | query_assistant_model | query_robot_status | query_task_status | query_navigation_status | query_battery | query_emergency_stop | query_perception_status | query_front_status | query_obstacle_status | query_navigation_safety | query_weather | query_environment | speak_last_result | open_chat | unknown",
    "command": "same as intent for executable/query commands, or null",
    "waypoint_alias": "用户提到的目标点别名，或 null",
    "waypoint_id": "仅可从可用 waypoint 列表选择，或 null",
    "target_class": "search_target/follow_target 的目标类别：bottle | cup | person | sports ball | chair | backpack，或 null",
    "target_color": "目标颜色：red | green | blue | yellow | white | black，或 null",
    "target_label": "目标的中文称呼，例如 红色水瓶，或 null",
    "confidence": "0.0 到 1.0",
    "need_confirm": "移动类任务 true，查询/暂停/继续可 false",
    "reason": "一句简短中文原因",
    "reply_text": "查询/开放问答类的中文回答；任务类确认提示；无法确定时为 null",
    "missing_slots": "缺少字段列表",
    "ask_text": "需要追问时的中文问题，或 null",
}


COMPACT_SYSTEM_PROMPT = """你是云拓轮腿机器人的语音助手。把用户的话解析成一个 JSON 对象，只输出 JSON，不要输出其他文字。
字段：intent, waypoint_id, target_class, target_color, target_label, confidence；只有 open_chat 才写 reply_text。
intent 取值：
- go_to_waypoint 去某个点位，waypoint_id 只能从点位表里选
- start_patrol 巡逻；pause_task 暂停；resume_task 继续；return_home 返航回家
- search_target 找到某个物体并靠近；follow_target 跟随某人，target_class=person
- query_robot_status 本体状态；query_task_status 任务进度；query_battery 电量；query_emergency_stop 急停状态
- query_perception_status 看到了什么；query_front_status 前方情况；query_navigation_safety 前方是否安全
- query_self_identity 你是谁；query_capability 你能做什么；query_weather 天气
- open_chat 闲聊或常识问答，简短中文回答写进 reply_text，不能包含任务
- unknown 无法确定，或要求关急停、忽略故障、高速冲、撞东西、写代码、删文件等
target_class 只能是 bottle、cup、person、sports ball、chair、backpack；target_color 只能是 red、green、blue、yellow、white、black，没有就不写。
用不到的字段不要输出，但每个 JSON 都必须有 intent 和 confidence（0 到 1 的把握程度）。"""


def prompt_style(backend: str) -> str:
    """板载小模型（local）上下文只有 1K token，用精简提示；云端模型用完整提示。LLM_PROMPT_STYLE 可强制指定。"""
    style = os.getenv("LLM_PROMPT_STYLE", "").strip().lower()
    if style in {"compact", "full"}:
        return style
    return "compact" if backend == "local" else "full"


def build_compact_prompts(recognized_text: str, history: list[tuple[str, str]] | None = None) -> tuple[str, str]:
    waypoints = [item for item in waypoint_resolver.list_waypoints() if item.get("waypoint_id")]

    def _row(item: dict) -> str:
        name = item.get("name") or item["waypoint_id"]
        seen = {"".join(name.lower().split())}
        aliases = []
        for alias in item.get("aliases") or []:
            key = "".join(str(alias).lower().split())
            if key and not any(key in s for s in seen):
                seen.add(key)
                aliases.append(str(alias))
        return f"{item['waypoint_id']}={name}" + (f"（也叫{'、'.join(aliases[:3])}）" if aliases else "")

    table = "；".join(_row(item) for item in waypoints)
    sample = next((item for item in waypoints if item["waypoint_id"] != "home"), None)
    examples = []
    if sample is not None:
        alias = (sample.get("aliases") or [sample.get("name") or sample["waypoint_id"]])[0]
        examples.append((f"去{alias}看看", {"intent": "go_to_waypoint", "waypoint_id": sample["waypoint_id"],
                                             "confidence": 0.9}))
    examples.append(("帮我找一下蓝色的杯子", {
        "intent": "search_target", "target_class": "cup", "target_color": "blue", "target_label": "蓝色杯子",
        "confidence": 0.9}))
    examples.append(("太阳为什么是热的", {"intent": "open_chat", "confidence": 0.9,
                                         "reply_text": "太阳内部一直在发生核聚变，释放出大量的光和热。"}))
    examples.append(("你累不累", {"intent": "open_chat", "confidence": 0.9,
                                "reply_text": "不累，我电量充足，随时可以开工。"}))
    examples.append(("一加一等于几", {"intent": "open_chat", "confidence": 0.9,
                                     "reply_text": "一加一等于二。"}))
    shots = "\n".join(f"用户：{q}\n{json.dumps(a, ensure_ascii=False, separators=(',', ':'))}" for q, a in examples)
    system_prompt = f"{COMPACT_SYSTEM_PROMPT}\n示例：\n{shots}"
    history_lines = "".join(f"用户：{u}\n助手：{a}\n" for u, a in (history or [])[-3:])
    ask = ""
    if any(k in recognized_text for k in ("笑话", "故事", "冷知识")):
        ask = "\n（用户想要一个简短的笑话或小故事，用 reply_text 直接给出内容，不要反问。）"
    elif any(k in recognized_text for k in ("再讲一个", "再来一个", "还有吗")):
        ask = "\n（结合最近对话，用户想再来一个同类且不同的内容，不要重复之前给过的，用 reply_text 直接给出。）"
    user_prompt = (f"最近对话（仅供理解指代，如“再讲一个”“明天呢”）：\n{history_lines or '无'}\n"
                   f"点位表：{table or '无'}\n用户：{recognized_text}{ask}")
    return system_prompt, user_prompt


def build_prompts(recognized_text: str, *, style: str = "full",
                  history: list[tuple[str, str]] | None = None) -> tuple[str, str]:
    if style == "compact":
        return build_compact_prompts(recognized_text, history)
    waypoints = waypoint_resolver.list_waypoints()
    compact_waypoints = [
        {
            "waypoint_id": item.get("waypoint_id"),
            "name": item.get("name"),
            "aliases": item.get("aliases", []),
        }
        for item in waypoints
    ]
    user_payload = {
        "recognized_text": recognized_text,
        "allowed_intents": sorted(ALLOWED_INTENTS),
        "available_waypoints": compact_waypoints,
        "output_json_schema": JSON_SCHEMA,
        "safety_rules": [
            "不得编造 waypoint_id；目标点只能来自 available_waypoints。",
            "go_to_waypoint/start_patrol/return_home/search_target/follow_target 属于移动类任务，need_confirm 必须为 true。",
            "用户要求找到某个物体并移动到其附近（例如找到红色水瓶）时用 search_target，填 target_class/target_color/target_label；要求跟着自己或某人时用 follow_target，target_class=person。",
            "目标类别只能是 bottle/cup/person/sports ball/chair/backpack；其他物体返回 unknown。",
            "如果用户要求写代码、删除文件、随便高速移动、自由规划或无法确定任务，intent 返回 unknown。",
            "如果用户要求直接速度控制、关闭急停、忽略故障、撞过去，intent 返回 unknown。",
            "如果缺少目标点，intent 返回 unknown，并在 missing_slots 写 target_waypoint。",
            "查询身份、能力、安全规则、助手模型、状态、任务、导航、电量、急停、视觉、前方状况、天气时，只输出对应 query intent，不要编造外部数据。",
            "用户问前面有什么、前方安全吗、前方有没有人或障碍物时，使用 query_front_status/query_navigation_safety/query_obstacle_status，不要生成导航任务。",
            "开放问答使用 open_chat，可直接在 reply_text 给出简短回答；open_chat 不能包含 waypoint_id，不能触发机器人任务。",
            "开放回答不能声称大模型直接控制底盘或直接执行导航；涉及导航时，应说明会生成结构化任务候选，经本地安全校验和用户确认后交由机器人导航链路执行。",
        ],
    }
    return SYSTEM_PROMPT, json.dumps(user_payload, ensure_ascii=False)
