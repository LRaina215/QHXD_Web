import base64
import hashlib
import os
import subprocess
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


# Default style prompt for MiMO TTS — describes how the robot should speak
_MIMO_TTS_SYSTEM_PROMPT = (
    "用亲切友好的语气播报，语速略快（约1.25倍正常语速），吐字清晰，像一位得体的助手在和用户对话。"
)


class TTSService:
    def __init__(self) -> None:
        self._latest: TTSStatus | None = None
        self._recent_event_keys: dict[str, datetime] = {}
        self._last_normal_at: datetime | None = None

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

    def speak_with_policy(
        self,
        text: str,
        *,
        event_key: str | None = None,
        priority: str = "normal",
    ) -> TTSStatus:
        now = datetime.now(timezone.utc)
        self._prune_recent_events(now)
        if event_key and event_key in self._recent_event_keys:
            status = TTSStatus(
                backend=self._backend(),
                status="skipped",
                text=text,
                detail="TTS 事件已播报过，已按去重策略跳过。",
                updated_at=now,
            )
            self._latest = status
            return status

        if priority != "critical" and self._last_normal_at is not None:
            elapsed = (now - self._last_normal_at).total_seconds()
            if elapsed < self._normal_cooldown_seconds():
                status = TTSStatus(
                    backend=self._backend(),
                    status="skipped",
                    text=text,
                    detail=f"TTS 普通播报冷却中，{elapsed:.1f}s 内重复内容已跳过。",
                    updated_at=now,
                )
                self._latest = status
                return status

        status = self.speak(text)
        if event_key and status.status in {"generated", "failed"}:
            self._recent_event_keys[event_key] = now
        if priority != "critical" and status.status in {"generated", "failed"}:
            self._last_normal_at = now
        return status

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
    # MiMO TTS (OpenAI-compatible chat completions)
    # ------------------------------------------------------------------

    def _speak_online(self, text: str) -> TTSStatus:
        now = datetime.now(timezone.utc)
        backend = self._backend()
        audio_bytes, error_reason = self._call_mimo_tts(text)

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
        suffix = self._mimo_audio_format()
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

    def _call_mimo_tts(self, text: str) -> tuple[bytes | None, str | None]:
        api_key = os.getenv("MIMO_API_KEY", "").strip()
        base_url = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1").strip().rstrip("/")
        model = os.getenv("MIMO_TTS_MODEL", "mimo-v2.5-tts").strip()
        voice = os.getenv("MIMO_TTS_VOICE", "茉莉").strip()
        audio_format = self._mimo_audio_format()

        if not api_key:
            return None, "未配置 MIMO_API_KEY，无法调用 MiMO TTS。"

        url = f"{base_url}/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": _MIMO_TTS_SYSTEM_PROMPT},
                {"role": "assistant", "content": text},
            ],
            "audio": {
                "format": audio_format,
                "voice": voice,
            },
        }

        try:
            with httpx.Client(timeout=self._api_timeout(), trust_env=False) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "api-key": api_key,
                    },
                )
        except httpx.TimeoutException:
            return None, f"MiMO TTS API 超时（{self._api_timeout()}s）"
        except Exception as exc:
            return None, f"MiMO TTS API 请求异常：{type(exc).__name__}: {exc}"

        if not response.is_success:
            detail = (response.text or f"HTTP {response.status_code}")[:300]
            return None, detail

        try:
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            audio_data = message.get("audio", {}).get("data", "")
            if not audio_data:
                return None, "MiMO TTS 响应中未找到音频数据。"
            audio_bytes = base64.b64decode(audio_data)
            return audio_bytes, None
        except (base64.binascii.Error, Exception) as exc:
            return None, f"MiMO TTS 响应解析失败：{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # local speaker playback
    # ------------------------------------------------------------------

    def _maybe_local_play(self, audio_path: Path) -> None:
        if not self._local_play_enabled():
            return
        # Always fix ES8388 output before playing — some process keeps resetting it to 0%
        self._fix_es8388_output()
        player_cmd = os.getenv("TTS_PLAYER_CMD", "aplay -D plughw:2,0").strip()
        try:
            subprocess.Popen(
                player_cmd.split() + [str(audio_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    @staticmethod
    def _fix_es8388_output() -> None:
        import subprocess as _sp
        cmds = [
            ["amixer", "-c", "2", "sset", "Speaker", "on"],
            ["amixer", "-c", "2", "sset", "Headphone", "on"],
            ["amixer", "-c", "2", "sset", "PCM", "95%"],
            ["amixer", "-c", "2", "sset", "Output 1", "90%"],
            ["amixer", "-c", "2", "sset", "Output 2", "90%"],
        ]
        for cmd in cmds:
            try:
                _sp.run(cmd, capture_output=True, timeout=2)
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
    def _mimo_audio_format() -> str:
        return os.getenv("MIMO_TTS_FORMAT", "wav").strip().lower() or "wav"

    @staticmethod
    def _api_timeout() -> float:
        try:
            return float(os.getenv("TTS_API_TIMEOUT", "15"))
        except ValueError:
            return 15.0

    def _prune_recent_events(self, now: datetime) -> None:
        max_age = self._event_dedup_seconds()
        stale = [
            key for key, timestamp in self._recent_event_keys.items()
            if (now - timestamp).total_seconds() > max_age
        ]
        for key in stale:
            self._recent_event_keys.pop(key, None)

    @staticmethod
    def _event_dedup_seconds() -> float:
        try:
            return max(10.0, float(os.getenv("TTS_EVENT_DEDUP_SECONDS", "3600")))
        except ValueError:
            return 3600.0

    @staticmethod
    def _normal_cooldown_seconds() -> float:
        try:
            return max(0.0, float(os.getenv("TTS_NORMAL_COOLDOWN_SECONDS", "1.5")))
        except ValueError:
            return 1.5


tts_service = TTSService()
