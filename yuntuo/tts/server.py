"""板载离线语音合成服务（sherpa-onnx，CPU）：模型常驻内存，后端 TTS_BACKEND=local + TTS_LOCAL_URL 调用。

  python -m yuntuo.tts_server --kind matcha --model-dir ~/models/tts/matcha-icefall-zh-baker \
      --vocoder ~/models/tts/vocoders/hifigan_v2.onnx

  GET  /health
  POST /tts      {"text": "...", "speed": 1.0}  ->  audio/wav（16 bit 单声道，采样率随模型）

RK3588 实测（绑 4 个 A76）：matcha-icefall-zh-en + vocos-16khz-univ 加载约 3.4 s，一句话 0.5~0.7 s（RTF≈0.16），
中英混读（"B 点"、"FPGA" 能读出来）；matcha-icefall-zh-baker 只认中文，会吞掉字母；vits-melo-tts-zh_en int8 RTF≈3.3，太慢。
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import threading
import time
import wave
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence

log = logging.getLogger("yuntuo_tts")

MAX_TEXT_CHARS = 300
MAX_BODY_BYTES = 16 * 1024
RULE_FSTS = ("phone", "date", "number", "new_heteronym")


def encode_wav(samples: Sequence[float], sample_rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def model_files(kind: str, model_dir: Path, vocoder: Path | None = None) -> dict[str, str]:
    """从模型目录找出 sherpa-onnx 需要的文件（与 k2-fsa 发布包的目录结构一致）。"""
    def need(name: str) -> str:
        path = model_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"{model_dir} 缺少 {name}")
        return str(path)

    files: dict[str, str] = {"tokens": need("tokens.txt")}
    if (model_dir / "lexicon.txt").is_file():
        files["lexicon"] = str(model_dir / "lexicon.txt")
    if (model_dir / "dict").is_dir():
        files["dict_dir"] = str(model_dir / "dict")
    onnx = sorted(p for p in model_dir.glob("*.onnx"))
    if kind == "matcha":
        acoustic = [p for p in onnx if p.name.startswith("model-steps")] or onnx
        if not acoustic:
            raise FileNotFoundError(f"{model_dir} 没有声学模型 *.onnx")
        if vocoder is None or not vocoder.is_file():
            raise FileNotFoundError("matcha 需要 --vocoder（例如 hifigan_v2.onnx）")
        files["acoustic_model"] = str(acoustic[0])
        files["vocoder"] = str(vocoder)
    elif kind == "vits":
        if not onnx:
            raise FileNotFoundError(f"{model_dir} 没有 *.onnx")
        preferred = [p for p in onnx if ".int8." in p.name] or onnx
        files["model"] = str(preferred[0])
    else:
        raise ValueError(f"不支持的模型类型：{kind}")
    if (model_dir / "espeak-ng-data").is_dir():           # 中英混合模型（matcha-icefall-zh-en）的英文部分
        files["data_dir"] = str(model_dir / "espeak-ng-data")
    fsts = []
    for stem in RULE_FSTS:                                # 有的包叫 phone.fst，有的叫 phone-zh.fst
        fsts += sorted(str(p) for p in model_dir.glob(f"{stem}*.fst"))
    files["rule_fsts"] = ",".join(fsts)
    return files


def load_sherpa(kind: str, files: dict[str, str], threads: int) -> Any:
    import sherpa_onnx

    common = {k: files[k] for k in ("lexicon", "tokens", "dict_dir", "data_dir") if k in files}
    if kind == "matcha":
        model = sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(acoustic_model=files["acoustic_model"],
                                                           vocoder=files["vocoder"], **common),
            num_threads=threads, provider="cpu")
    else:
        model = sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=files["model"], **common),
            num_threads=threads, provider="cpu")
    config = sherpa_onnx.OfflineTtsConfig(model=model, rule_fsts=files.get("rule_fsts", ""), max_num_sentences=1)
    if not config.validate():
        raise RuntimeError("sherpa-onnx TTS 配置校验失败，检查模型文件")
    return sherpa_onnx.OfflineTts(config)


class SpeechService:
    """串行合成 + 小 LRU（任务播报的固定句子会反复出现）。synth(text, speed) -> (samples, sample_rate)。"""

    def __init__(self, synth: Callable[[str, float], tuple[Sequence[float], int]], model_id: str, *,
                 default_speed: float = 1.0, cache_size: int = 32) -> None:
        self._synth = synth
        self.model_id = model_id
        self.default_speed = default_speed
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, float], bytes] = OrderedDict()
        self._cache_size = cache_size
        self.requests = 0
        self.last: dict | None = None
        self.started_at = time.time()

    def speak(self, text: str, speed: float | None = None) -> bytes:
        text = " ".join(str(text).split())
        if not text:
            raise ValueError("text 为空")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"text 超过 {MAX_TEXT_CHARS} 字")
        speed = round(float(speed or self.default_speed), 2)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("speed 需在 0.5~2.0")
        key = (text, speed)
        with self._lock:
            self.requests += 1
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                self.last = {"chars": len(text), "cached": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                return cached
            t0 = time.monotonic()
            samples, rate = self._synth(text, speed)
            gen_s = time.monotonic() - t0
            if len(samples) == 0:
                raise RuntimeError("合成结果为空")
            data = encode_wav(samples, rate)
            audio_s = len(samples) / float(rate)
            self.last = {"chars": len(text), "cached": False, "gen_s": round(gen_s, 3), "audio_s": round(audio_s, 2),
                         "rtf": round(gen_s / audio_s, 3) if audio_s else None,
                         "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            self._cache[key] = data
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        log.info("tts %s", self.last)
        return data

    def health(self) -> dict:
        return {"status": "ok", "service": "yuntuo-tts", "model": self.model_id, "requests": self.requests,
                "cached": len(self._cache), "uptime_s": round(time.time() - self.started_at, 1), "last": self.last}


def make_handler(service: SpeechService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, json.dumps(service.health(), ensure_ascii=False).encode("utf-8"), "application/json")
            else:
                self._error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/tts":
                self._error(404, "not found")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > MAX_BODY_BYTES:
                    raise ValueError("请求体大小不合法")
                body = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                audio = service.speak(body.get("text", ""), body.get("speed"))
            except (ValueError, json.JSONDecodeError) as exc:
                self._error(400, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("tts failed")
                self._error(500, f"合成失败：{exc}")
                return
            self._send(200, audio, "audio/wav")

        def _error(self, status: int, message: str) -> None:
            self._send(status, json.dumps({"error": message}, ensure_ascii=False).encode("utf-8"), "application/json")

        def _send(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

    return Handler


def _parse_cpus(spec: str) -> set[int]:
    cpus: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            cpus.update(range(int(lo), int(hi) + 1))
        elif part:
            cpus.add(int(part))
    return cpus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="云拓板载离线语音合成服务（sherpa-onnx）")
    ap.add_argument("--kind", choices=["matcha", "vits"], default=os.getenv("TTS_MODEL_KIND", "matcha"))
    ap.add_argument("--model-dir", default=os.getenv("TTS_MODEL_DIR"))
    ap.add_argument("--vocoder", default=os.getenv("TTS_VOCODER_PATH"))
    ap.add_argument("--threads", type=int, default=int(os.getenv("TTS_NUM_THREADS", "4")))
    ap.add_argument("--cpus", default=os.getenv("TTS_CPUS", "4-7"), help="绑核（RK3588 的 A76 是 4-7），空串表示不绑")
    ap.add_argument("--speed", type=float, default=float(os.getenv("TTS_SPEED", "1.0")))
    ap.add_argument("--sid", type=int, default=int(os.getenv("TTS_SPEAKER_ID", "0")))
    ap.add_argument("--host", default=os.getenv("TTS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("TTS_PORT", "8081")))
    ap.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.model_dir:
        ap.error("缺少 --model-dir 或 TTS_MODEL_DIR")
    if args.cpus and hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, _parse_cpus(args.cpus))
    model_dir = Path(args.model_dir).expanduser()
    files = model_files(args.kind, model_dir, Path(args.vocoder).expanduser() if args.vocoder else None)
    t0 = time.monotonic()
    tts = load_sherpa(args.kind, files, args.threads)
    log.info("模型已加载（%.1f s）：%s，采样率 %d", time.monotonic() - t0, model_dir, tts.sample_rate)

    def synth(text: str, speed: float) -> tuple[Sequence[float], int]:
        audio = tts.generate(text, sid=args.sid, speed=speed)
        return audio.samples, audio.sample_rate

    service = SpeechService(synth, model_dir.name, default_speed=args.speed)
    service.speak("你好")                     # 预热：第一次推理会慢一些
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    server.daemon_threads = True
    log.info("监听 http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
