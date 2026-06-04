from __future__ import annotations

import json

from app.services.voice.llm_schema import ALLOWED_INTENTS
from app.services.waypoint_resolver import waypoint_resolver

SYSTEM_PROMPT = """你是灵巡 Sentinel 的受控型智能语音助手。
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
    "intent": "go_to_waypoint | start_patrol | pause_task | resume_task | return_home | query_self_identity | query_capability | query_safety_rule | query_assistant_model | query_robot_status | query_task_status | query_battery | query_emergency_stop | query_perception_status | query_weather | query_environment | speak_last_result | open_chat | unknown",
    "command": "same as intent for executable/query commands, or null",
    "waypoint_alias": "用户提到的目标点别名，或 null",
    "waypoint_id": "仅可从可用 waypoint 列表选择，或 null",
    "confidence": "0.0 到 1.0",
    "need_confirm": "移动类任务 true，查询/暂停/继续可 false",
    "reason": "一句简短中文原因",
    "reply_text": "查询/开放问答类的中文回答；任务类确认提示；无法确定时为 null",
    "missing_slots": "缺少字段列表",
    "ask_text": "需要追问时的中文问题，或 null",
}


def build_prompts(recognized_text: str) -> tuple[str, str]:
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
            "go_to_waypoint/start_patrol/return_home 属于移动类任务，need_confirm 必须为 true。",
            "如果用户要求写代码、删除文件、随便高速移动、自由规划或无法确定任务，intent 返回 unknown。",
            "如果用户要求直接速度控制、关闭急停、忽略故障、撞过去，intent 返回 unknown。",
            "如果缺少目标点，intent 返回 unknown，并在 missing_slots 写 target_waypoint。",
            "查询身份、能力、安全规则、助手模型、状态、任务、电量、急停、视觉、天气时，只输出对应 query intent，不要编造外部数据。",
            "开放问答使用 open_chat，可直接在 reply_text 给出简短回答；open_chat 不能包含 waypoint_id，不能触发机器人任务。",
            "开放回答不能声称大模型直接控制底盘或直接执行导航；涉及导航时，应说明会生成结构化任务候选，经本地安全校验和用户确认后交由机器人导航链路执行。",
        ],
    }
    return SYSTEM_PROMPT, json.dumps(user_payload, ensure_ascii=False)
