import os
from datetime import datetime, timezone

from app.schemas import TTSStatus


class TTSService:
    def __init__(self) -> None:
        self._latest: TTSStatus | None = None

    def speak(self, text: str) -> TTSStatus:
        backend = os.getenv("TTS_BACKEND", "mock").strip().lower() or "mock"
        if backend != "mock":
            status = TTSStatus(
                backend=backend,
                status="unsupported",
                text=text,
                detail=f"当前未实现 TTS_BACKEND={backend}，已保留文本回复。",
                updated_at=datetime.now(timezone.utc),
            )
        else:
            status = TTSStatus(
                backend="mock",
                status="generated",
                text=text,
                audio_path=None,
                detail="mock TTS 已生成文本播报占位，不阻塞主流程。",
                updated_at=datetime.now(timezone.utc),
            )
        self._latest = status
        return status

    def latest(self) -> TTSStatus | None:
        return self._latest


tts_service = TTSService()
