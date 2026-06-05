import hashlib
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.schemas import TTSStatus


def _tts_dir() -> Path:
    raw = os.getenv("TTS_AUDIO_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "tts"


def _tts_max_files() -> int:
    try:
        return max(1, int(os.getenv("TTS_MAX_AUDIO_FILES", "20")))
    except ValueError:
        return 20


def _cleanup_old_audio() -> None:
    tts_dir = _tts_dir()
    if not tts_dir.exists():
        return
    max_files = _tts_max_files()
    if max_files <= 0:
        return
    files = sorted(
        [p for p in tts_dir.iterdir() if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[max_files:]:
        try:
            stale.unlink()
        except Exception:
            pass


class TTSService:
    def __init__(self) -> None:
        self._latest: TTSStatus | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> TTSStatus:
        backend = self._backend()
        if backend == "online":
            return self._speak_online(text)
        if backend == "local":
            return self._speak_online(text)
        return self._speak_mock(text)

    def latest(self) -> TTSStatus | None:
        return self._latest

    # ------------------------------------------------------------------
    # mock
    # ------------------------------------------------------------------

    def _speak_mock(self, text: str) -> TTSStatus:
        now = datetime.now(timezone.utc)
        status = TTSStatus(
            backend="mock",
            status="generated",
            text=text,
            detail="mock TTS 已生成文本播报占位，不阻塞主流程。",
            created_at=now,
            updated_at=now,
        )
        self._latest = status
        return status

    # ------------------------------------------------------------------
    # online / local real TTS
    # ------------------------------------------------------------------

    def _speak_online(self, text: str) -> TTSStatus:
        now = datetime.now(timezone.utc)
        backend = self._backend()
        audio_bytes, error_reason = self._call_tts_api(text)

        if audio_bytes is None:
            status = TTSStatus(
                backend=backend,
                status="failed",
                text=text,
                detail=f"TTS 请求失败：{error_reason}",
                error_reason=error_reason,
                created_at=now,
                updated_at=now,
            )
            self._latest = status
            return status

        tts_dir = _tts_dir()
        tts_dir.mkdir(parents=True, exist_ok=True)
        request_id = uuid.uuid4().hex[:12]
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        suffix = self._audio_suffix()
        filename = f"tts_{timestamp}_{request_id}.{suffix}"
        audio_path = tts_dir / filename

        audio_path.write_bytes(audio_bytes)
        _cleanup_old_audio()

        audio_url = f"/api/voice/tts/audio/{filename}"

        status = TTSStatus(
            backend=backend,
            status="generated",
            text=text,
            audio_path=str(audio_path),
            audio_url=audio_url,
            detail=f"TTS 音频已生成：{filename}",
            created_at=now,
            updated_at=now,
        )
        self._latest = status

        self._maybe_local_play(audio_path)

        return status

    def _call_tts_api(self, text: str) -> tuple[bytes | None, str | None]:
        api_url = os.getenv("TTS_ONLINE_API_URL", "").strip()
        api_key = os.getenv("TTS_ONLINE_API_KEY", "").strip()
        model = os.getenv("TTS_ONLINE_MODEL", "").strip()
        voice = os.getenv("TTS_ONLINE_VOICE", "zh-CN-XiaoxiaoNeural").strip()

        if not api_url:
            return None, "未配置 TTS_ONLINE_API_URL，无法调用在线 TTS。"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict = {"text": text, "voice": voice}
        if model:
            payload["model"] = model

        try:
            with httpx.Client(timeout=self._api_timeout(), trust_env=False) as client:
                response = client.post(api_url, json=payload, headers=headers)
        except httpx.TimeoutException:
            return None, f"TTS API 超时（{self._api_timeout()}s）"
        except Exception as exc:
            return None, f"TTS API 请求异常：{type(exc).__name__}: {exc}"

        if not response.is_success:
            detail = (response.text or f"HTTP {response.status_code}")[:300]
            return None, detail

        content_type = response.headers.get("content-type", "")
        if "audio" in content_type or len(response.content) > 100:
            audio_bytes = response.content
            if self._is_wav(audio_bytes) or self._is_mp3(audio_bytes) or len(audio_bytes) > 100:
                return audio_bytes, None
            return None, f"TTS 响应不是有效音频格式：{content_type[:80]}"

        try:
            data = response.json()
            audio_url_in_resp = data.get("audio_url") or data.get("url") or data.get("data", {}).get("audio_url", "")
            if audio_url_in_resp:
                return self._download_audio(audio_url_in_resp)
            raw = (response.text or "")[:300]
            return None, raw
        except Exception:
            raw = (response.text or "")[:300]
            return None, raw

    def _download_audio(self, url: str) -> tuple[bytes | None, str | None]:
        try:
            with httpx.Client(timeout=self._api_timeout(), trust_env=False) as client:
                resp = client.get(url)
                if resp.is_success:
                    return resp.content, None
                return None, f"下载 TTS 音频失败：HTTP {resp.status_code}"
        except Exception as exc:
            return None, f"下载 TTS 音频异常：{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # local speaker playback
    # ------------------------------------------------------------------

    def _maybe_local_play(self, audio_path: Path) -> None:
        if not self._local_play_enabled():
            return
        player_cmd = os.getenv("TTS_PLAYER_CMD", "aplay -D plughw:2,0").strip()
        try:
            subprocess.Popen(
                player_cmd.split() + [str(audio_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _local_play_enabled(self) -> bool:
        val = os.getenv("TTS_AUTO_PLAY_LOCAL", "false").strip().lower()
        return val in {"1", "true", "yes", "on"}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _backend() -> str:
        return os.getenv("TTS_BACKEND", "mock").strip().lower() or "mock"

    @staticmethod
    def _audio_suffix() -> str:
        return os.getenv("TTS_AUDIO_FORMAT", "wav").strip().lower() or "wav"

    @staticmethod
    def _api_timeout() -> float:
        try:
            return float(os.getenv("TTS_API_TIMEOUT", "15"))
        except ValueError:
            return 15.0

    @staticmethod
    def _is_wav(data: bytes) -> bool:
        return len(data) >= 4 and data[:4] == b"RIFF"

    @staticmethod
    def _is_mp3(data: bytes) -> bool:
        return len(data) >= 2 and (data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3" or data[:2] == b"\xff\xf2")


tts_service = TTSService()
