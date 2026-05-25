import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas import VoiceTextCommandRequest


@dataclass(frozen=True)
class ASRResult:
    recognized_text: str
    raw_text: str | None
    backend: str
    success: bool
    error: str | None = None
    asr_time_s: float | None = None
    model_load_time_s: float | None = None


class ASRService:
    """ASR backend facade for mock text and FunASR wav transcription."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_load_time_s: float | None = None

    @property
    def backend(self) -> str:
        return os.getenv("ASR_BACKEND", "mock").strip().lower() or "mock"

    def transcribe_text_mock(self, request: VoiceTextCommandRequest) -> VoiceTextCommandRequest:
        return VoiceTextCommandRequest(
            text=request.text,
            source=request.source or "asr-text-mock",
            requested_by=request.requested_by,
            use_llm=request.use_llm,
        )

    def transcribe_audio_file(self, audio_path: str) -> ASRResult:
        backend = self.backend
        if backend == "mock":
            return self._transcribe_mock(audio_path)
        if backend == "funasr":
            return self._transcribe_funasr(audio_path)
        return ASRResult(
            recognized_text="",
            raw_text=None,
            backend=backend,
            success=False,
            error=f"不支持的 ASR_BACKEND：{backend}",
        )

    def _transcribe_mock(self, audio_path: str) -> ASRResult:
        recognized_text = os.getenv("VOICE_MOCK_RECOGNIZED_TEXT", "").strip()
        if not recognized_text:
            recognized_text = self._mock_text_from_filename(audio_path)
        return ASRResult(
            recognized_text=recognized_text,
            raw_text=recognized_text,
            backend="mock",
            success=bool(recognized_text),
            error=None if recognized_text else "mock backend 未提供识别文本。",
            asr_time_s=0.0,
            model_load_time_s=0.0,
        )

    def _transcribe_funasr(self, audio_path: str) -> ASRResult:
        started_at = time.perf_counter()
        model_was_loaded = self._model is not None
        try:
            model = self._get_funasr_model()
            model_load_time_s = 0.0 if model_was_loaded else self._model_load_time_s
            result = model.generate(
                input=audio_path,
                cache={},
                language=os.getenv("FUNASR_LANGUAGE", "zh"),
                use_itn=self._env_bool("FUNASR_USE_ITN", True),
                batch_size_s=float(os.getenv("FUNASR_BATCH_SIZE_S", "60")),
                merge_vad=True,
                merge_length_s=15,
            )
            raw_text = self._extract_text(result)
            recognized_text = self._postprocess_text(raw_text)
            return ASRResult(
                recognized_text=recognized_text,
                raw_text=raw_text,
                backend="funasr",
                success=bool(recognized_text),
                error=None if recognized_text else "FunASR 未识别到有效文本。",
                asr_time_s=round(time.perf_counter() - started_at, 3),
                model_load_time_s=model_load_time_s,
            )
        except Exception as exc:
            return ASRResult(
                recognized_text="",
                raw_text=None,
                backend="funasr",
                success=False,
                error=f"FunASR 识别失败：{exc}",
                asr_time_s=round(time.perf_counter() - started_at, 3),
                model_load_time_s=0.0 if model_was_loaded else self._model_load_time_s,
            )

    def _get_funasr_model(self):
        if self._model is not None:
            return self._model

        model_path = self._required_path("FUNASR_MODEL_PATH")
        vad_model_path = self._required_path("FUNASR_VAD_MODEL_PATH")
        device = os.getenv("FUNASR_DEVICE", "cpu")
        if self._env_bool("FUNASR_DISABLE_UPDATE", True):
            os.environ.setdefault("MODELSCOPE_OFFLINE", "1")

        started_at = time.perf_counter()
        try:
            from funasr import AutoModel
        except Exception as exc:
            raise RuntimeError("ASR_BACKEND=funasr 但当前 Python 环境未安装 funasr。") from exc

        kwargs: dict[str, Any] = {
            "model": str(model_path),
            "vad_model": str(vad_model_path),
            "device": device,
            "trust_remote_code": True,
            "vad_kwargs": {"max_single_segment_time": 30000},
        }
        try:
            kwargs["disable_update"] = self._env_bool("FUNASR_DISABLE_UPDATE", True)
            self._model = AutoModel(**kwargs)
        except TypeError:
            kwargs.pop("disable_update", None)
            self._model = AutoModel(**kwargs)

        self._model_load_time_s = round(time.perf_counter() - started_at, 3)
        return self._model

    @staticmethod
    def _required_path(env_key: str) -> Path:
        raw_path = os.getenv(env_key, "").strip()
        if not raw_path:
            raise RuntimeError(f"缺少环境变量 {env_key}。")
        path = Path(raw_path)
        if not path.exists():
            raise RuntimeError(f"{env_key} 指向的路径不存在：{path}")
        return path

    @staticmethod
    def _extract_text(result: Any) -> str:
        if isinstance(result, list):
            return "".join(ASRService._extract_text(item) for item in result)
        if isinstance(result, dict):
            text = result.get("text") or result.get("sentence") or result.get("raw_text") or ""
            return str(text)
        return str(result or "")

    @staticmethod
    def _postprocess_text(raw_text: str) -> str:
        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess

            processed = rich_transcription_postprocess(raw_text)
        except Exception:
            processed = raw_text
        return ASRService._clean_text(processed)

    @staticmethod
    def _clean_text(raw_text: str) -> str:
        without_tags = re.sub(r"<\|[^>]+\|>", "", raw_text)
        without_brackets = re.sub(r"[\[\]{}'\"]", "", without_tags)
        return re.sub(r"\s+", "", without_brackets).strip("，。！？,.!?：:")

    @staticmethod
    def _mock_text_from_filename(audio_path: str) -> str:
        stem = Path(audio_path).stem
        mapping = {
            "cmd_201": "去二零一实验室",
            "pause_task": "暂停任务",
            "resume_task": "继续任务",
            "return_home": "返回起点",
            "start_patrol": "开始巡检",
            "unknown_command": "打开窗户",
        }
        for key, value in mapping.items():
            if key in stem:
                return value
        return ""

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        raw_value = os.getenv(key)
        if raw_value is None:
            return default
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}


asr_service = ASRService()
