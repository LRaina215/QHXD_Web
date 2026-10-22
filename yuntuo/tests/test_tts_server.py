"""板载语音合成服务的纯 Python 部分：模型文件发现、wav 编码、缓存与 HTTP 接口（假合成器，不需要 sherpa-onnx）。"""
import io
import json
import threading
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer

import pytest

from yuntuo.tts.server import SpeechService, make_handler, model_files


def _touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_model_files_matcha_and_vits(tmp_path):
    m = tmp_path / "matcha-icefall-zh-baker"
    for name in ("tokens.txt", "lexicon.txt", "model-steps-3.onnx", "phone.fst", "date.fst", "number.fst",
                 "dict/jieba.dict.utf8"):
        _touch(m / name)
    voc = tmp_path / "hifigan_v2.onnx"
    _touch(voc)
    files = model_files("matcha", m, voc)
    assert files["acoustic_model"].endswith("model-steps-3.onnx")
    assert files["vocoder"] == str(voc)
    assert files["rule_fsts"].split(",") == [str(m / n) for n in ("phone.fst", "date.fst", "number.fst")]
    with pytest.raises(FileNotFoundError):
        model_files("matcha", m, None)

    v = tmp_path / "vits"
    for name in ("tokens.txt", "model.onnx", "model.int8.onnx"):
        _touch(v / name)
    files = model_files("vits", v)
    assert files["model"].endswith("model.int8.onnx")
    assert "lexicon" not in files and files["rule_fsts"] == ""


def test_speech_service_encodes_wav_and_caches():
    calls = []

    def synth(text, speed):
        calls.append((text, speed))
        return [0.0, 0.5, -0.5, 1.5] * 4000, 16000

    svc = SpeechService(synth, "fake")
    first = svc.speak("  你好，云拓  ")
    with wave.open(io.BytesIO(first)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 16000)
    assert svc.speak("你好，云拓") == first
    assert calls == [("你好，云拓", 1.0)]
    assert svc.health()["last"]["cached"] is True
    with pytest.raises(ValueError):
        svc.speak("")
    with pytest.raises(ValueError):
        svc.speak("好", speed=3)


def test_http_endpoint_returns_wav_and_json_errors():
    svc = SpeechService(lambda text, speed: ([0.1] * 1600, 16000), "fake")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        req = urllib.request.Request(f"{base}/tts", data=json.dumps({"text": "到达 B 点"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=5) as r:
            assert r.headers["Content-Type"] == "audio/wav"
            assert r.read().startswith(b"RIFF")
        bad = urllib.request.Request(f"{base}/tts", data=b"{}", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as err:
            opener.open(bad, timeout=5)
        assert err.value.code == 400
        with opener.open(f"{base}/health", timeout=5) as r:
            assert json.loads(r.read())["requests"] == 1
    finally:
        server.shutdown()
