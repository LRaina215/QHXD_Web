import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class AudioRecordResult:
    success: bool
    audio_path: Path | None
    duration: int
    audio_device: str
    error: str | None = None
    detail: str | None = None


class AudioRecorder:
    """Records a short wav file from the RK3588 USB microphone via arecord."""

    def record(self, duration: int) -> AudioRecordResult:
        config = self._config(duration)
        record_dir = config["record_dir"]
        record_dir.mkdir(parents=True, exist_ok=True)
        audio_path = record_dir / self._unique_filename()
        command = [
            "arecord",
            "-D",
            config["device"],
            "-r",
            str(config["sample_rate"]),
            "-c",
            str(config["channels"]),
            "-f",
            config["audio_format"],
            "-d",
            str(duration),
            str(audio_path),
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=duration + 5,
                check=False,
            )
        except FileNotFoundError:
            return AudioRecordResult(
                success=False,
                audio_path=audio_path,
                duration=duration,
                audio_device=config["device"],
                error="audio_record_failed",
                detail="arecord command not found",
            )
        except subprocess.TimeoutExpired as exc:
            return AudioRecordResult(
                success=False,
                audio_path=audio_path,
                duration=duration,
                audio_device=config["device"],
                error="audio_record_failed",
                detail=f"arecord timeout: {exc}",
            )

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown arecord error").strip()
            return AudioRecordResult(
                success=False,
                audio_path=audio_path,
                duration=duration,
                audio_device=config["device"],
                error="audio_record_failed",
                detail=f"arecord failed: {detail}",
            )

        if not audio_path.exists() or audio_path.stat().st_size <= 44:
            return AudioRecordResult(
                success=False,
                audio_path=audio_path,
                duration=duration,
                audio_device=config["device"],
                error="empty_audio_file",
                detail="录音文件为空。",
            )

        return AudioRecordResult(
            success=True,
            audio_path=audio_path,
            duration=duration,
            audio_device=config["device"],
        )

    def default_duration(self) -> int:
        return self._bounded_int(os.getenv("AUDIO_RECORD_SECONDS", "3"), 3, minimum=1, maximum=10)

    def default_keep_audio(self) -> bool:
        return self._env_bool("VOICE_KEEP_RECORDINGS", True)

    def _config(self, duration: int) -> dict:
        return {
            "device": os.getenv("AUDIO_DEVICE", "plughw:CARD=Device,DEV=0"),
            "sample_rate": self._bounded_int(os.getenv("AUDIO_SAMPLE_RATE", "16000"), 16000, minimum=8000),
            "channels": self._bounded_int(os.getenv("AUDIO_CHANNELS", "1"), 1, minimum=1, maximum=2),
            "audio_format": os.getenv("AUDIO_FORMAT", "S16_LE"),
            "record_dir": self._record_dir(),
            "duration": duration,
        }

    @staticmethod
    def _record_dir() -> Path:
        raw_path = os.getenv("VOICE_RECORD_DIR", "").strip()
        if raw_path:
            return Path(raw_path).expanduser()
        return Path(__file__).resolve().parents[2] / "data" / "voice_records"

    @staticmethod
    def _unique_filename() -> str:
        now = datetime.now()
        millis = now.microsecond // 1000
        return f"voice_{now:%Y%m%d_%H%M%S}_{millis:03d}_{uuid.uuid4().hex[:8]}.wav"

    @staticmethod
    def _bounded_int(raw_value: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
        value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        raw_value = os.getenv(key)
        if raw_value is None:
            return default
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}


audio_recorder = AudioRecorder()
