"""librkllmrt.so（rknn-llm runtime v1.3.x）的 ctypes 绑定，只覆盖文本对话用到的接口。

结构体布局按 rkllm-runtime/Linux/librkllm_api/include/rkllm.h（release-v1.3.1）逐字段对应；
升级运行库时先比对头文件，字段顺序或类型变了这里必须同步改。
"""
from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass

RKLLM_RUN_NORMAL, RKLLM_RUN_WAITING, RKLLM_RUN_FINISH, RKLLM_RUN_ERROR = 0, 1, 2, 3
RKLLM_INPUT_PROMPT = 0
RKLLM_INFER_GENERATE = 0
BIG_CORES_MASK = 0xF0          # RK3588 的 4 个 A76（cpu4-7）


class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104),
    ]


class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("ignore_eos_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMEmbedInput(ctypes.Structure):
    _fields_ = [("embed", ctypes.POINTER(ctypes.c_float)), ("n_tokens", ctypes.c_size_t)]


class RKLLMTokenInput(ctypes.Structure):
    _fields_ = [("input_ids", ctypes.POINTER(ctypes.c_int32)), ("n_tokens", ctypes.c_size_t)]


class _ImageInput(ctypes.Structure):
    _fields_ = [
        ("image_embed", ctypes.POINTER(ctypes.c_float)), ("n_image_tokens", ctypes.c_size_t),
        ("n_image", ctypes.c_size_t), ("image_start", ctypes.c_char_p), ("image_end", ctypes.c_char_p),
        ("image_content", ctypes.c_char_p), ("image_width", ctypes.c_size_t), ("image_height", ctypes.c_size_t),
    ]


class _VideoInput(ctypes.Structure):
    _fields_ = [
        ("video_embed", ctypes.POINTER(ctypes.c_float)), ("n_frame_tokens", ctypes.c_size_t),
        ("n_frame_per_video", ctypes.c_size_t), ("n_video", ctypes.c_size_t), ("video_start", ctypes.c_char_p),
        ("video_end", ctypes.c_char_p), ("video_content", ctypes.c_char_p), ("frame_width", ctypes.c_size_t),
        ("frame_height", ctypes.c_size_t),
    ]


class _AudioInput(ctypes.Structure):
    _fields_ = [
        ("audio_embed", ctypes.POINTER(ctypes.c_float)), ("n_audio_tokens", ctypes.c_size_t),
        ("n_audio", ctypes.c_size_t), ("audio_start", ctypes.c_char_p), ("audio_end", ctypes.c_char_p),
        ("audio_content", ctypes.c_char_p),
    ]


class RKLLMMultiModalInput(ctypes.Structure):
    _fields_ = [("prompt", ctypes.c_char_p), ("image", _ImageInput), ("video", _VideoInput), ("audio", _AudioInput)]


class _InputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", RKLLMEmbedInput),
        ("token_input", RKLLMTokenInput),
        ("multimodal_input", RKLLMMultiModalInput),
    ]


class RKLLMInput(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("enable_thinking", ctypes.c_bool),
        ("input_type", ctypes.c_int),
        ("u", _InputUnion),
    ]


class RKLLMLoraParam(ctypes.Structure):
    _fields_ = [("lora_adapter_name", ctypes.c_char_p)]


class RKLLMPromptCacheParam(ctypes.Structure):
    _fields_ = [("save_prompt_cache", ctypes.c_int), ("prompt_cache_path", ctypes.c_char_p)]


class RKLLMSamplingParam(ctypes.Structure):
    _fields_ = [
        ("top_k", ctypes.c_int32), ("top_p", ctypes.c_float), ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float), ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float), ("mirostat", ctypes.c_int32), ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
    ]


class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("sampling_params", ctypes.POINTER(RKLLMSamplingParam)),
        ("keep_history", ctypes.c_int),
        ("max_new_tokens", ctypes.c_int32),
    ]


class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [("hidden_states", ctypes.POINTER(ctypes.c_float)), ("embd_size", ctypes.c_int),
                ("num_tokens", ctypes.c_int)]


class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [("logits", ctypes.POINTER(ctypes.c_float)), ("vocab_size", ctypes.c_int), ("num_tokens", ctypes.c_int)]


class RKLLMPerfStat(ctypes.Structure):
    _fields_ = [("prefill_time_ms", ctypes.c_float), ("prefill_tokens", ctypes.c_int),
                ("generate_time_ms", ctypes.c_float), ("generate_tokens", ctypes.c_int),
                ("memory_usage_mb", ctypes.c_float)]


class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int32),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
        ("perf", RKLLMPerfStat),
    ]


ResultCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)
TokenizerCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
                                     ctypes.POINTER(ctypes.c_int32), ctypes.c_int32)
EmbedCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint64,
                                 ctypes.c_void_p, ctypes.c_uint64)


class RKLLMCallback(ctypes.Structure):
    _fields_ = [
        ("result_callback", ResultCallback), ("result_userdata", ctypes.c_void_p),
        ("tokenizer_callback", TokenizerCallback), ("tokenizer_userdata", ctypes.c_void_p),
        ("embed_callback", EmbedCallback), ("embed_userdata", ctypes.c_void_p),
    ]


@dataclass
class Generation:
    text: str
    finish_reason: str          # stop | length | error | abort
    prompt_tokens: int
    completion_tokens: int
    prefill_ms: float
    generate_ms: float
    memory_mb: float
    wall_ms: float


class RKLLMEngine:
    """单实例、串行推理。rkllm_run 是同步调用，回调在同一次调用里逐 token 触发。"""

    def __init__(self, lib_path: str, model_path: str, *, max_context_len: int = 1024, max_new_tokens: int = 256,
                 cpus_mask: int = BIG_CORES_MASK, embed_flash: bool = True) -> None:
        self._lib = ctypes.CDLL(lib_path)
        self._bind()
        self._lock = threading.Lock()
        self._chunks: list[bytes] = []
        self._state = RKLLM_RUN_NORMAL
        self._perf = RKLLMPerfStat()
        self._tokens = 0
        self._callback_fn = ResultCallback(self._on_result)   # 必须持有引用，否则 C 侧回调时已被回收
        self._callbacks = RKLLMCallback()
        self._callbacks.result_callback = self._callback_fn
        self._template_system: str | None = None
        self.max_context_len = max_context_len
        self.max_new_tokens = max_new_tokens

        param = self._lib.rkllm_createDefaultParam()
        param.model_path = model_path.encode("utf-8")
        param.max_context_len = max_context_len
        param.max_new_tokens = max_new_tokens
        param.skip_special_token = True
        param.is_async = False
        param.extend_param.base_domain_id = 0
        param.extend_param.embed_flash = 1 if embed_flash else 0
        param.extend_param.n_batch = 1
        param.extend_param.use_cross_attn = 0
        param.extend_param.enabled_cpus_mask = cpus_mask
        param.extend_param.enabled_cpus_num = bin(cpus_mask).count("1")
        self._handle = ctypes.c_void_p()
        ret = self._lib.rkllm_init(ctypes.byref(self._handle), ctypes.byref(param), ctypes.byref(self._callbacks))
        if ret != 0:
            raise RuntimeError(f"rkllm_init 失败（返回 {ret}）：检查模型与运行库版本、NPU 驱动")

    def _bind(self) -> None:
        lib = self._lib
        lib.rkllm_createDefaultParam.restype = RKLLMParam
        lib.rkllm_createDefaultParam.argtypes = []
        lib.rkllm_init.restype = ctypes.c_int
        lib.rkllm_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(RKLLMParam),
                                   ctypes.POINTER(RKLLMCallback)]
        lib.rkllm_run.restype = ctypes.c_int
        lib.rkllm_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam),
                                  ctypes.c_void_p]
        lib.rkllm_abort.restype = ctypes.c_int
        lib.rkllm_abort.argtypes = [ctypes.c_void_p]
        lib.rkllm_destroy.restype = ctypes.c_int
        lib.rkllm_destroy.argtypes = [ctypes.c_void_p]
        lib.rkllm_set_chat_template.restype = ctypes.c_int
        lib.rkllm_set_chat_template.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.rkllm_clear_kv_cache.restype = ctypes.c_int
        lib.rkllm_clear_kv_cache.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                                             ctypes.POINTER(ctypes.c_int)]

    def _on_result(self, result, _userdata, state) -> int:
        self._state = state
        if state == RKLLM_RUN_NORMAL and result and result.contents.text:
            self._chunks.append(result.contents.text)
            self._tokens += 1
        elif state == RKLLM_RUN_FINISH and result:
            ctypes.memmove(ctypes.byref(self._perf), ctypes.byref(result.contents.perf), ctypes.sizeof(RKLLMPerfStat))
        return 0

    def set_template(self, system_block: str, prefix: str, postfix: str) -> None:
        if system_block == self._template_system:
            return
        ret = self._lib.rkllm_set_chat_template(self._handle, system_block.encode("utf-8"), prefix.encode("utf-8"),
                                                postfix.encode("utf-8"))
        if ret != 0:
            raise RuntimeError(f"rkllm_set_chat_template 失败（返回 {ret}）")
        self._template_system = system_block

    def generate(self, prompt: str, *, template: tuple[str, str, str], max_new_tokens: int | None = None,
                 temperature: float | None = None, top_p: float | None = None, timeout_s: float = 60.0) -> Generation:
        with self._lock:
            self.set_template(*template)
            self._chunks, self._tokens, self._state = [], 0, RKLLM_RUN_NORMAL
            self._perf = RKLLMPerfStat()
            prompt_bytes = prompt.encode("utf-8")
            inp = RKLLMInput()
            inp.role = b"user"
            inp.enable_thinking = False
            inp.input_type = RKLLM_INPUT_PROMPT
            inp.prompt_input = prompt_bytes
            infer = RKLLMInferParam()
            infer.mode = RKLLM_INFER_GENERATE
            infer.keep_history = 0
            limit = max(1, min(int(max_new_tokens or self.max_new_tokens), self.max_new_tokens))
            infer.max_new_tokens = limit
            sampling = None
            if temperature is not None or top_p is not None:
                sampling = RKLLMSamplingParam(top_k=1 if (temperature or 0) <= 0.01 else 20,
                                              top_p=0.8 if top_p is None else float(top_p),
                                              temperature=max(0.01, float(temperature or 0.01)),
                                              repeat_penalty=1.1, frequency_penalty=0.0, presence_penalty=0.0,
                                              mirostat=0, mirostat_tau=5.0, mirostat_eta=0.1)
                infer.sampling_params = ctypes.pointer(sampling)
            aborted = threading.Event()

            def _abort() -> None:
                aborted.set()
                self._lib.rkllm_abort(self._handle)

            timer = threading.Timer(timeout_s, _abort)
            timer.daemon = True
            t0 = time.monotonic()
            timer.start()
            try:
                ret = self._lib.rkllm_run(self._handle, ctypes.byref(inp), ctypes.byref(infer), None)
            finally:
                timer.cancel()
            wall_ms = (time.monotonic() - t0) * 1000.0
            text = b"".join(self._chunks).decode("utf-8", errors="replace")
            if aborted.is_set():
                reason = "abort"
            elif ret != 0 or self._state == RKLLM_RUN_ERROR:
                reason = "error"
            elif self._tokens >= limit:
                reason = "length"
            else:
                reason = "stop"
            perf = self._perf
            return Generation(text=text, finish_reason=reason, prompt_tokens=int(perf.prefill_tokens),
                              completion_tokens=int(perf.generate_tokens) or self._tokens,
                              prefill_ms=float(perf.prefill_time_ms), generate_ms=float(perf.generate_time_ms),
                              memory_mb=float(perf.memory_usage_mb), wall_ms=wall_ms)

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._lib.rkllm_destroy(self._handle)
                self._handle = ctypes.c_void_p()
