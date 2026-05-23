from __future__ import annotations

import json
import os

from app.services.intent_parser import ParsedIntent, intent_parser
from app.services.voice.llm_client import llm_client
from app.services.voice.llm_prompt import build_prompts
from app.services.voice.llm_schema import LLMIntent
from app.services.voice.llm_safety import llm_safety_validator


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class LLMIntentParser:
    def parse(self, text: str, *, use_llm: bool | None = None) -> ParsedIntent:
        rule_result = intent_parser.parse(text)
        if not self._should_try_llm(text, rule_result, use_llm):
            return rule_result

        system_prompt, user_prompt = build_prompts(text)
        client_response = llm_client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            force_enable=use_llm,
        )
        if not client_response.success or not client_response.content:
            if rule_result.intent is not None and rule_result.confidence >= 0.9 and not self._looks_complex(text):
                return rule_result
            return ParsedIntent(
                intent=None,
                confidence=0.0,
                need_confirm=True,
                detail=f"LLM 未可用或调用失败：{client_response.error}，未触发任务。",
                parser="llm",
                llm_backend=client_response.backend,
                llm_model=client_response.model,
            )

        try:
            data = json.loads(self._strip_json_fence(client_response.content))
            llm_result = LLMIntent.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return ParsedIntent(
                intent=None,
                confidence=0.0,
                need_confirm=True,
                detail="LLM 输出不是合法 JSON，未触发任务。",
                parser="llm",
                llm_backend=client_response.backend,
                llm_model=client_response.model,
                llm_raw_output=client_response.content if self._debug_raw() else None,
            )

        safe = llm_safety_validator.validate(llm_result)
        if not safe.ok:
            return ParsedIntent(
                intent="unknown",
                confidence=safe.confidence,
                need_confirm=True,
                detail=safe.detail,
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
        if rule_result.intent is None:
            return True
        if rule_result.need_confirm or rule_result.confidence < 0.75:
            return True
        return self._looks_complex(text)

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
