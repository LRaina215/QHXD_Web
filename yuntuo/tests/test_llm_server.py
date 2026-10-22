"""板载大模型服务的纯 Python 部分：ChatML 拼装、JSON 截取、OpenAI 兼容响应（用假引擎，不需要 NPU）。"""
import ctypes
import json

from yuntuo.llm import rkllm
from yuntuo.llm.server import ChatService, extract_json_object, render_chatml


class FakeEngine:
    max_context_len = 1024
    max_new_tokens = 128

    def __init__(self, text="", finish="stop"):
        self.text, self.finish = text, finish
        self.calls = []

    def generate(self, prompt, *, template, max_new_tokens=None, temperature=None, top_p=None, timeout_s=60.0):
        self.calls.append({"prompt": prompt, "template": template, "max_new_tokens": max_new_tokens,
                           "temperature": temperature})
        return rkllm.Generation(text=self.text, finish_reason=self.finish, prompt_tokens=12, completion_tokens=8,
                                prefill_ms=10.0, generate_ms=50.0, memory_mb=1700.0, wall_ms=61.0)


def test_render_chatml_puts_system_in_template_and_folds_history():
    template, prompt = render_chatml([
        {"role": "system", "content": "只输出 JSON"},
        {"role": "user", "content": "去A点"},
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": [{"type": "text", "text": "再去B点"}]},
    ])
    assert template[0] == "<|im_start|>system\n只输出 JSON<|im_end|>\n"
    full = template[1] + prompt + template[2]
    assert full == ("<|im_start|>user\n去A点<|im_end|>\n<|im_start|>assistant\n{}<|im_end|>\n"
                    "<|im_start|>user\n再去B点<|im_end|>\n<|im_start|>assistant\n")


def test_render_chatml_rejects_trailing_assistant():
    try:
        render_chatml([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    except ValueError:
        return
    raise AssertionError("应拒绝以 assistant 结尾的 messages")


def test_extract_json_object_skips_prose_and_braces_in_strings():
    text = '好的：{"intent":"open_chat","reply_text":"花括号 } 也行"} 以上'
    assert extract_json_object(text) == {"intent": "open_chat", "reply_text": "花括号 } 也行"}
    assert extract_json_object("{坏的} 然后 {\"a\": 1}") == {"a": 1}
    assert extract_json_object("没有 JSON") is None


def test_chat_service_json_mode_and_errors():
    engine = FakeEngine(text='```json\n{"intent": "pause_task", "confidence": 0.9}\n```')
    service = ChatService(engine, "qwen2.5-1.5b-instruct")
    status, body = service.chat({"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "停"}],
                                 "max_tokens": 64, "response_format": {"type": "json_object"}})
    assert status == 200
    assert json.loads(body["choices"][0]["message"]["content"]) == {"intent": "pause_task", "confidence": 0.9}
    assert body["usage"]["total_tokens"] == 20
    assert engine.calls[0]["max_new_tokens"] == 64
    assert engine.calls[0]["temperature"] == 0.0          # json_object 强制贪心解码
    assert service.health()["last"]["ok"] is True

    assert service.chat({"messages": [], "stream": True})[0] == 400
    service.engine = FakeEngine(finish="error")
    status, body = service.chat({"messages": [{"role": "user", "content": "x"}]})
    assert status == 500 and "上下文" in body["error"]["message"]


def test_ctypes_layout_matches_rkllm_h_on_64bit():
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return
    assert ctypes.sizeof(rkllm.RKLLMExtendParam) == 120
    assert rkllm.RKLLMParam.extend_param.offset == 60
    assert rkllm.RKLLMInput.u.offset == 16
    assert rkllm.RKLLMInferParam.keep_history.offset == 32
    assert rkllm.RKLLMResult.perf.offset == 48
