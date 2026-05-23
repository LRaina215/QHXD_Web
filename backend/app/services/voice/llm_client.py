from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def _load_env_file_once() -> None:
    if os.environ.get("QHXD_ENV_FILE_LOADED") == "1":
        return
    os.environ["QHXD_ENV_FILE_LOADED"] = "1"
    roots = [Path(__file__).resolve().parents[4], Path(__file__).resolve().parents[3]]
    for root in roots:
        env_path = root / ".env"
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMClientConfig:
    backend: str
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float
    max_tokens: int
    temperature: float
    debug_raw: bool
    force_enable: bool = False

    @property
    def enabled(self) -> bool:
        backend_enabled = self.backend == "deepseek"
        env_enabled = self.force_enable or _env_bool("LLM_ENABLE", _env_bool("DEEPSEEK_ENABLE", False))
        return backend_enabled and env_enabled and bool(self.api_key)


@dataclass(frozen=True)
class LLMClientResponse:
    success: bool
    content: str | None = None
    error: str | None = None
    backend: str = "deepseek"
    model: str | None = None
    raw_response: dict | None = None


class DeepSeekClient:
    def config(self, force_enable: bool | None = None) -> LLMClientConfig:
        _load_env_file_once()
        try:
            timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "5"))
        except ValueError:
            timeout = 5.0
        try:
            max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "512"))
        except ValueError:
            max_tokens = 512
        try:
            temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))
        except ValueError:
            temperature = 0.1
        backend = os.getenv("LLM_BACKEND", "deepseek").strip().lower()
        return LLMClientConfig(
            backend=backend,
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            timeout_seconds=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            debug_raw=_env_bool("LLM_DEBUG_RAW", False),
            force_enable=bool(force_enable),
        )

    def chat_json(self, *, system_prompt: str, user_prompt: str, force_enable: bool | None = None) -> LLMClientResponse:
        config = self.config(force_enable=force_enable)
        if not config.enabled:
            return LLMClientResponse(success=False, error="llm-disabled-or-missing-api-key", model=config.model)
        url = f"{config.base_url}/v1/chat/completions"
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:200]
            return LLMClientResponse(success=False, error=f"deepseek-http-{exc.code}: {detail}", model=config.model)
        except TimeoutError:
            return LLMClientResponse(success=False, error="deepseek-timeout", model=config.model)
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            return LLMClientResponse(success=False, error=f"deepseek-error: {type(exc).__name__}", model=config.model)

        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return LLMClientResponse(success=False, error="deepseek-invalid-response", model=config.model, raw_response=raw)
        return LLMClientResponse(success=True, content=str(content), model=config.model, raw_response=raw if config.debug_raw else None)


llm_client = DeepSeekClient()
