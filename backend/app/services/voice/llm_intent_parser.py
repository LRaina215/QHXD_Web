from __future__ import annotations

import json
import os
from dataclasses import replace

from app.services.intent_parser import ParsedIntent, intent_parser
from app.services.voice.llm_client import llm_client
from app.services.voice.llm_prompt import build_prompts, prompt_style
from app.services.waypoint_resolver import waypoint_resolver
from app.services.voice.llm_schema import LLMIntent
from app.services.voice.llm_safety import _threshold as confidence_threshold, llm_safety_validator, normalize_class


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class LLMIntentParser:
    def __init__(self) -> None:
        self._history: list[tuple[str, str]] = []          # (用户原话, 一句话结局)，给"再讲一个"这类追问提供指代上下文

    def parse(self, text: str, *, use_llm: bool | None = None) -> ParsedIntent:
        rule_result = intent_parser.parse(text)
        if not self._should_try_llm(text, rule_result, use_llm):
            self._remember(text, rule_result.intent, rule_result.detail)
            return rule_result

        style = prompt_style(llm_client.config(force_enable=use_llm).backend)
        system_prompt, user_prompt = build_prompts(text, style=style, history=self._history)
        creative = any(k in text for k in ("笑话", "故事", "冷知识", "再讲一个", "再来一个", "还有吗"))
        client_response = llm_client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            force_enable=use_llm,
            temperature=0.8 if creative else None,
        )
        if not client_response.success or not client_response.content:
            if rule_result.intent is not None and rule_result.confidence >= 0.9 and not self._looks_complex(text):
                return rule_result
            return ParsedIntent(
                intent=None,
                confidence=0.0,
                need_confirm=True,
                detail="我这边理解出了点问题，稍等再试一次，或者直接说要做什么（去 A 点、找红色水瓶、跟着我）。",
                parser="llm",
                llm_backend=client_response.backend,
                llm_model=client_response.model,
            )

        try:
            data = json.loads(self._strip_json_fence(client_response.content))
            llm_result = LLMIntent.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            # 创作类请求带温度后，小模型常直接输出纯文本（笑话/故事），不再包 JSON：当闲聊回复用
            plain = (client_response.content or "").strip().strip("`").strip()
            if creative and plain and "{" not in plain and 2 <= len(plain) <= 200:
                self._remember(text, "open_chat", plain)
                return ParsedIntent(
                    intent="open_chat",
                    confidence=0.75,
                    need_confirm=False,
                    detail=plain,
                    parser="llm",
                    llm_backend=client_response.backend,
                    llm_model=client_response.model,
                )
            if self._rule_can_back_up(rule_result):
                return rule_result
            return ParsedIntent(
                intent=None,
                confidence=0.0,
                need_confirm=True,
                detail="我这边理解出了点问题，稍等再试一次，或者直接说要做什么（去 A 点、找红色水瓶、跟着我）。",
                parser="llm",
                llm_backend=client_response.backend,
                llm_model=client_response.model,
                llm_raw_output=client_response.content if self._debug_raw() else None,
            )

        self._remember(text, llm_result.intent, llm_result.reply_text or llm_result.reason)
        safe = llm_safety_validator.validate(self._fill_target_slots(llm_result, rule_result))
        grounded = self._check_grounded(text, safe)
        if safe.ok and grounded is not None:
            if self._rule_can_back_up(rule_result) and rule_result.intent == grounded[0]:
                return rule_result
            return ParsedIntent(
                intent="unknown",
                confidence=0.0,
                need_confirm=True,
                detail=grounded[1],
                parser="llm",
                llm_backend=client_response.backend,
                llm_model=client_response.model,
            )
        if not safe.ok:
            # 板载小模型常漏掉 confidence（解析成 0）：规则有把握时用规则结果；模型明确判 unknown 且有把握时仍以模型为准
            if self._rule_can_back_up(rule_result) and llm_result.confidence < confidence_threshold():
                return rule_result
            detail = safe.detail
            normalized_text = "".join(text.lower().split())
            if (rule_result.intent == "go_to_waypoint" and not rule_result.payload.get("waypoint_id")
                    and any(k in normalized_text for k in ("去", "到", "回", "前往", "导航"))):
                detail = "你说的这个点我没有，能说个具体的点位吗？比如 A 点、B 点、C 点或起点。"
            elif (rule_result.intent == "search_target" and not rule_result.payload.get("target_class")
                    and any(k in normalized_text for k in ("找", "寻", "搜"))):
                detail = "想找什么？我能找水瓶、杯子、人、球、椅子或背包。"
            return ParsedIntent(
                intent="unknown",
                confidence=safe.confidence,
                need_confirm=True,
                detail=detail,
                parser="llm",
                llm_backend=client_response.backend,
                llm_model=client_response.model,
                llm_raw_output=client_response.content if self._debug_raw() else None,
            )
        return ParsedIntent(
            intent=safe.intent,
            payload=safe.payload,
            confidence=safe.confidence,
            need_confirm=safe.need_confirm,
            detail=safe.detail,
            parser="llm",
            llm_backend=client_response.backend,
            llm_model=client_response.model,
            llm_raw_output=client_response.content if self._debug_raw() else None,
        )

    def _should_try_llm(self, text: str, rule_result: ParsedIntent, use_llm: bool | None) -> bool:
        if use_llm is False:
            return False
        if use_llm is None and not _env_bool("LLM_ENABLE", _env_bool("DEEPSEEK_ENABLE", False)):
            return False
        if rule_result.intent == "unknown" and rule_result.confidence >= 0.9:
            return False
        if rule_result.intent is None:
            return True
        if self._rule_is_confident(text, rule_result):
            return False
        if rule_result.need_confirm or rule_result.confidence < 0.75:
            return True
        return self._looks_complex(text)

    @staticmethod
    def _fill_target_slots(llm_result: LLMIntent, rule_result: ParsedIntent) -> LLMIntent:
        """找物 / 跟随：模型和规则认的是同一类目标时，模型漏掉的颜色、称呼用规则从原话里抽出来的补上。"""
        if llm_result.intent not in {"search_target", "follow_target"} or rule_result.intent != llm_result.intent:
            return llm_result
        rule_class = rule_result.payload.get("target_class")
        if not rule_class or normalize_class(llm_result.target_class or rule_class) != rule_class:
            return llm_result
        return replace(
            llm_result,
            target_class=llm_result.target_class or str(rule_class),
            target_color=llm_result.target_color or (str(rule_result.payload["color"]) if rule_result.payload.get("color") else None),
            target_label=llm_result.target_label or (str(rule_result.payload["label"]) if rule_result.payload.get("label") else None),
        )

    @staticmethod
    def _check_grounded(text: str, safe) -> tuple[str, str] | None:
        """小模型会把用户没说的点位 / 目标编出来（"去那个点"→A点、"找东西"→绿色瓶子）。
        校验通过的意图还要能在原话里找到依据，找不到就改为追问。返回 (意图, 追问话术) 表示不成立。"""
        normalized = "".join(text.lower().split())
        command = safe.command
        if command == "go_to_waypoint":
            waypoint_id = str(safe.payload.get("waypoint_id") or "")
            waypoint = next((w for w in waypoint_resolver.list_waypoints()
                             if str(w.get("waypoint_id")) == waypoint_id), None)
            aliases = [waypoint_id, str(waypoint.get("name") or ""), *[str(a) for a in (waypoint or {}).get("aliases", [])]]
            mentioned = any(alias and "".join(alias.lower().split()) in normalized for alias in aliases)
            if not mentioned:
                return command, "你说的这个点我没有，能说个具体的点位吗？比如 A 点、B 点、C 点或起点。"
        elif command == "search_target":
            from app.services.intent_parser import TARGET_CLASS_WORDS
            mentioned = any(word in normalized for word, _ in TARGET_CLASS_WORDS) or "人" in normalized
            if not mentioned:
                return command, "想找什么？我能找水瓶、杯子、人、球、椅子或背包。"
        return None

    @staticmethod
    def _rule_can_back_up(rule_result: ParsedIntent) -> bool:
        return rule_result.intent not in {None, "unknown"} and rule_result.confidence >= 0.9

    def _rule_is_confident(self, text: str, rule_result: ParsedIntent) -> bool:
        """规则解析有把握（≥0.9）且句子不复杂：常用短句（跟着我、去 A 点、返航…）不必再等几秒大模型。
        运动类照样要用户确认；危险说法已在规则里直接拒绝。"""
        return (
            rule_result.intent not in {None, "unknown"}
            and rule_result.confidence >= 0.9
            and not self._looks_complex(text)
        )

    def _remember(self, text: str, intent: str | None, summary: str) -> None:
        """只记闲聊内容：查询/任务的摘要把小模型带偏（问"太阳为什么是热的"会答成天气），追问靠规则记忆。"""
        if intent != "open_chat" or not summary:
            return
        self._history.append((text[:40], str(summary)[:40]))
        self._history = self._history[-4:]

    @staticmethod
    def _looks_complex(text: str) -> bool:
        normalized = "".join(text.lower().split())
        complex_markers = ["帮我", "样品", "拿", "把", "送到", "我想让", "能不能", "请你"]
        return len(normalized) >= 10 and any(marker in normalized for marker in complex_markers)

    @staticmethod
    def _strip_json_fence(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
        return stripped

    @staticmethod
    def _debug_raw() -> bool:
        return _env_bool("LLM_DEBUG_RAW", False)


llm_intent_parser = LLMIntentParser()
