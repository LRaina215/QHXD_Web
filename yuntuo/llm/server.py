"""板载离线大模型服务：OpenAI 兼容子集（只监听 127.0.0.1），后端 LLM_BACKEND=local 直接调用。

  python -m yuntuo.llm_server --model ~/models/llm/qwen2.5-1.5b-instruct-w8a8/Qwen2.5-1.5B-Instruct.rkllm \
      --lib /opt/rkllm/1.3.1/librkllmrt.so

  GET  /health                 模型、运行库、最近一次推理耗时
  GET  /v1/models
  POST /v1/chat/completions    messages / max_tokens / temperature / top_p / response_format={"type":"json_object"}
                               不支持 stream、tools、多选（n>1）。

json_object 模式下没有约束解码，只在输出里截取第一个完整 JSON 对象；截不到就原样返回，由后端判失败。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

log = logging.getLogger("yuntuo_llm")

DEFAULT_SYSTEM = "You are a helpful assistant."
CHATML = ("<|im_start|>system\n{system}<|im_end|>\n", "<|im_start|>user\n", "<|im_end|>\n<|im_start|>assistant\n")
MAX_BODY_BYTES = 256 * 1024


class Engine(Protocol):
    max_context_len: int
    max_new_tokens: int

    def generate(self, prompt: str, *, template: tuple[str, str, str], max_new_tokens: int | None = None,
                 temperature: float | None = None, top_p: float | None = None, timeout_s: float = 60.0) -> Any: ...


def _text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):     # [{"type":"text","text":...}]
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def render_chatml(messages: list[dict]) -> tuple[tuple[str, str, str], str]:
    """系统提示放进 rkllm 的 chat template（运行库可复用它的 KV），其余轮次拼成最后一条 user 输入。"""
    if not messages:
        raise ValueError("messages 为空")
    system = "\n".join(_text_of(m) for m in messages if m.get("role") == "system").strip() or DEFAULT_SYSTEM
    turns = [m for m in messages if m.get("role") in {"user", "assistant", "tool"}]
    if not turns or turns[-1].get("role") == "assistant":
        raise ValueError("最后一条消息必须是 user")
    sys_tpl, prefix, postfix = CHATML
    parts: list[str] = []
    prev_role = None
    for m in turns:
        role, text = m.get("role"), _text_of(m)
        if prev_role is None:
            parts.append(text)
        elif role == "assistant":
            parts.append(f"{postfix}{text}<|im_end|>\n")
        elif prev_role == "assistant":
            parts.append(f"{prefix}{text}")
        else:                                   # 连续的 user / tool 合并成一条
            parts.append(f"\n{text}")
        prev_role = role
    return (sys_tpl.format(system=system), prefix, postfix), "".join(parts)


def extract_json_object(text: str) -> dict | None:
    """输出里第一个能解析的 {...}（跳过字符串里的括号）。"""
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


class ChatService:
    def __init__(self, engine: Engine, model_id: str, *, timeout_s: float = 60.0) -> None:
        self.engine = engine
        self.model_id = model_id
        self.timeout_s = timeout_s
        self.started_at = time.time()
        self._stats_lock = threading.Lock()
        self.requests = 0
        self.last: dict | None = None

    def health(self) -> dict:
        with self._stats_lock:
            return {"status": "ok", "service": "yuntuo-llm", "model": self.model_id,
                    "max_context_len": self.engine.max_context_len, "max_new_tokens": self.engine.max_new_tokens,
                    "requests": self.requests, "uptime_s": round(time.time() - self.started_at, 1), "last": self.last}

    def models(self) -> dict:
        return {"object": "list", "data": [{"id": self.model_id, "object": "model", "owned_by": "local"}]}

    def chat(self, body: dict) -> tuple[int, dict]:
        if body.get("stream"):
            return 400, _error("stream 未实现", "invalid_request_error")
        messages = body.get("messages")
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            return 400, _error("messages 必须是对象数组", "invalid_request_error")
        try:
            template, prompt = render_chatml(messages)
        except ValueError as exc:
            return 400, _error(str(exc), "invalid_request_error")
        json_mode = (body.get("response_format") or {}).get("type") == "json_object"
        # 结构化输出用贪心解码：同一句话每次结果一致，小模型也不容易漏字段
        temperature = 0.0 if json_mode else _float_or_none(body.get("temperature"))
        gen = self.engine.generate(prompt, template=template, max_new_tokens=_int_or_none(body.get("max_tokens")),
                                   temperature=temperature,
                                   top_p=_float_or_none(body.get("top_p")), timeout_s=self.timeout_s)
        if gen.finish_reason in {"error", "abort"}:
            detail = "推理超时被中止" if gen.finish_reason == "abort" else "推理出错（可能超出上下文长度）"
            self._record(gen, ok=False)
            return 500, _error(detail, "server_error")
        content = gen.text.strip()
        if json_mode:
            obj = extract_json_object(content)
            if obj is not None:
                content = json.dumps(obj, ensure_ascii=False)
        self._record(gen, ok=True)
        return 200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_id,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "length" if gen.finish_reason == "length" else "stop"}],
            "usage": {"prompt_tokens": gen.prompt_tokens, "completion_tokens": gen.completion_tokens,
                      "total_tokens": gen.prompt_tokens + gen.completion_tokens},
        }

    def _record(self, gen: Any, *, ok: bool) -> None:
        with self._stats_lock:
            self.requests += 1
            self.last = {"ok": ok, "finish_reason": gen.finish_reason, "prompt_tokens": gen.prompt_tokens,
                         "completion_tokens": gen.completion_tokens, "prefill_ms": round(gen.prefill_ms, 1),
                         "generate_ms": round(gen.generate_ms, 1), "wall_ms": round(gen.wall_ms, 1),
                         "memory_mb": round(gen.memory_mb, 1), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        log.info("chat %s", self.last)


def _error(message: str, kind: str) -> dict:
    return {"error": {"message": message, "type": kind, "param": None, "code": None}}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def make_handler(service: ChatService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(200, service.health())
            elif self.path == "/v1/models":
                self._json(200, service.models())
            else:
                self._json(404, _error("not found", "invalid_request_error"))

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/v1/chat/completions", "/chat/completions"}:
                self._json(404, _error("not found", "invalid_request_error"))
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > MAX_BODY_BYTES:
                    raise ValueError
                body = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError
            except Exception:
                self._json(400, _error("请求体必须是 JSON 对象", "invalid_request_error"))
                return
            try:
                status, payload = service.chat(body)
            except Exception as exc:  # noqa: BLE001
                log.exception("chat failed")
                status, payload = 500, _error(f"内部错误：{exc}", "server_error")
            self._json(status, payload)

        def _json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="云拓板载离线大模型服务（rknn-llm）")
    ap.add_argument("--model", default=os.getenv("RKLLM_MODEL_PATH"), help=".rkllm 模型文件")
    ap.add_argument("--lib", default=os.getenv("RKLLM_LIB_PATH", "/opt/rkllm/1.3.1/librkllmrt.so"))
    ap.add_argument("--model-id", default=os.getenv("LLM_LOCAL_MODEL", "qwen2.5-1.5b-instruct"))
    ap.add_argument("--host", default=os.getenv("RKLLM_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("RKLLM_PORT", "8080")))
    ap.add_argument("--max-context", type=int, default=int(os.getenv("RKLLM_MAX_CONTEXT", "1024")),
                    help="不能超过转换模型时的 max_context")
    ap.add_argument("--max-new-tokens", type=int, default=int(os.getenv("RKLLM_MAX_NEW_TOKENS", "256")))
    ap.add_argument("--timeout", type=float, default=float(os.getenv("RKLLM_TIMEOUT_SECONDS", "60")))
    ap.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.model or not os.path.isfile(os.path.expanduser(args.model)):
        ap.error("找不到模型文件：--model 或 RKLLM_MODEL_PATH")
    from yuntuo.llm.rkllm import RKLLMEngine

    t0 = time.monotonic()
    engine = RKLLMEngine(args.lib, os.path.expanduser(args.model), max_context_len=args.max_context,
                         max_new_tokens=args.max_new_tokens)
    log.info("模型已加载（%.1f s）：%s", time.monotonic() - t0, args.model)
    service = ChatService(engine, args.model_id, timeout_s=args.timeout)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    server.daemon_threads = True
    log.info("监听 http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()
    return 0
