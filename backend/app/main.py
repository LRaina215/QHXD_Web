import asyncio
import os
import re
import tempfile
import time
import wave
from pathlib import Path
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app.schemas import (
    AlertsResponse,
    CommandLogsResponse,
    CurrentTaskResponse,
    ExternalWeatherLatestResponse,
    GoToWaypointRequest,
    HealthResponse,
    ImuLatestResponse,
    MissionActionResponse,
    MissionActionResult,
    ModeSwitchRequest,
    ModeSwitchResponse,
    NavigationLatestResponse,
    NavigationMapMetadataResponse,
    NavigationMapUpdateRequest,
    NavigationSnapshot,
    NavigationUpdateResponse,
    NavigationUpdateResult,
    NucImuUpdateRequest,
    NucImuUpdateResponse,
    NucStateUpdateRequest,
    NucStateUpdateResponse,
    PauseMissionRequest,
    PerceptionDetectionStatusRequest,
    PerceptionDetectionStatusResponse,
    PerceptionDetectionStatusResult,
    ResumeMissionRequest,
    ReturnHomeRequest,
    SmartCommandRequest,
    SmartCommandResponse,
    SmartCommandResult,
    SpeakRequest,
    SpeakResponse,
    StartPatrolRequest,
    StateLatestResponse,
    TTSLatestResponse,
    VoiceAudioCommandResponse,
    VoiceAudioCommandResult,
    VoiceCommandResponse,
    VoiceConfirmCommandRequest,
    VoiceConfirmCommandResponse,
    VoiceRecordCommandRequest,
    VoiceRecordCommandResponse,
    VoiceRecordCommandResult,
    VoiceTextCommandRequest,
)
from app.services.asr_service import ASRResult, asr_service
from app.services.audio_recorder import audio_recorder
from app.services.imu_store import imu_store
from app.services.mission_gateway import mission_gateway
from app.services.mode_manager import mode_manager
from app.services.navigation_store import navigation_store
from app.services.mock_state import mock_state_service
from app.services.nuc_adapter import nuc_adapter
from app.services.persistence import persistence
from app.services.smart_voice_service import smart_voice_service
from app.services.state_store import state_store
from app.services.tts_service import tts_service
from app.services.voice_entry import voice_entry_service
from app.services.weather_provider import weather_provider
from app.services.ws_manager import ws_manager


async def _mock_state_loop() -> None:
    while True:
        if state_store.get_system_mode().mode == "mock":
            state = state_store.publish_mock_state(mock_state_service.tick())
            if state is not None:
                await ws_manager.broadcast_state(state)
        await asyncio.sleep(1)


async def _real_health_loop() -> None:
    while True:
        state = mode_manager.poll_real_health()
        if state is not None:
            await ws_manager.broadcast_state(state)
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    mock_state_service.initialize()
    state_store.initialize(mock_state_service.get_latest_state())
    imu_store.initialize()
    mode_manager.initialize(state_store.get_latest_state())
    state_task = asyncio.create_task(_mock_state_loop())
    health_task = asyncio.create_task(_real_health_loop())
    try:
        yield
    finally:
        state_task.cancel()
        health_task.cancel()
        with suppress(asyncio.CancelledError):
            await state_task
        with suppress(asyncio.CancelledError):
            await health_task


app = FastAPI(title="RK3588 Middleware", version="0.1.0", lifespan=lifespan)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
YOLO_OUTPUT_DIR = PROJECT_ROOT / "experiments" / "rknn_yolo" / "outputs"
DEFAULT_LATEST_FRAME_PATH = YOLO_OUTPUT_DIR / "latest_camera_detection.jpg"
LATEST_FRAME_CANDIDATES = (
    YOLO_OUTPUT_DIR / "latest_camera_detection.jpg",
    YOLO_OUTPUT_DIR / "latest_hik_detection.jpg",
)


def _latest_frame_path() -> Path:
    configured_path = os.getenv("PERCEPTION_LATEST_FRAME_PATH")
    if configured_path:
        return Path(configured_path).expanduser()

    existing_candidates = [path for path in LATEST_FRAME_CANDIDATES if path.exists() and path.is_file()]
    if existing_candidates:
        return max(existing_candidates, key=lambda path: path.stat().st_mtime)
    return DEFAULT_LATEST_FRAME_PATH


def _perception_latest_frame_max_age_s() -> float:
    try:
        return float(os.getenv("PERCEPTION_LATEST_FRAME_MAX_AGE_SECONDS", "10"))
    except ValueError:
        return 10.0


def _mjpeg_stream_interval_s() -> float:
    try:
        interval_ms = float(os.getenv("PERCEPTION_MJPEG_INTERVAL_MS", "200"))
    except ValueError:
        interval_ms = 200.0
    return max(0.05, interval_ms / 1000.0)


def _read_latest_frame_bytes() -> tuple[Path, bytes, float, int] | None:
    frame_path = _latest_frame_path()
    if not frame_path.exists() or not frame_path.is_file():
        return None

    stat_result = frame_path.stat()
    max_age_s = _perception_latest_frame_max_age_s()
    age_s = max(0.0, time.time() - stat_result.st_mtime)
    if max_age_s > 0 and age_s > max_age_s:
        return None

    data = frame_path.read_bytes()
    if not data:
        return None
    return frame_path, data, age_s, stat_result.st_mtime_ns


async def _mjpeg_frame_generator():
    boundary = b"--frame"
    last_mtime_ns = -1
    while True:
        latest = _read_latest_frame_bytes()
        if latest is not None:
            frame_path, data, age_s, mtime_ns = latest
            if mtime_ns != last_mtime_ns:
                last_mtime_ns = mtime_ns
                headers = (
                    boundary
                    + b"\r\n"
                    + b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(data)}\r\n".encode("ascii")
                    + f"X-Latest-Frame-Path: {frame_path}\r\n".encode("utf-8")
                    + f"X-Latest-Frame-Age: {age_s:.3f}\r\n\r\n".encode("ascii")
                )
                yield headers + data + b"\r\n"
        await asyncio.sleep(_mjpeg_stream_interval_s())


def _latest_frame_response():
    frame_path = _latest_frame_path()
    cache_headers = {"Cache-Control": "no-store, no-cache, must-revalidate"}
    if not frame_path.exists() or not frame_path.is_file():
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "latest_frame_not_found",
                "detail": f"最新识别图片不存在：{frame_path}",
            },
            headers=cache_headers,
        )

    max_age_s = _perception_latest_frame_max_age_s()
    age_s = max(0.0, time.time() - frame_path.stat().st_mtime)
    if max_age_s > 0 and age_s > max_age_s:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "latest_frame_stale",
                "detail": f"最新识别图片已过期：{frame_path}，age={age_s:.1f}s",
            },
            headers={**cache_headers, "X-Latest-Frame-Path": str(frame_path), "X-Latest-Frame-Age": f"{age_s:.3f}"},
        )

    return FileResponse(
        frame_path,
        media_type="image/jpeg",
        headers={
            **cache_headers,
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Latest-Frame-Path": str(frame_path),
            "X-Latest-Frame-Age": f"{age_s:.3f}",
        },
    )




def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _voice_max_upload_bytes() -> int:
    try:
        max_mb = float(os.getenv("VOICE_MAX_UPLOAD_MB", "20"))
    except ValueError:
        max_mb = 20.0
    return int(max_mb * 1024 * 1024)


def _voice_max_audio_seconds() -> float:
    try:
        return float(os.getenv("VOICE_MAX_AUDIO_SECONDS", "10"))
    except ValueError:
        return 10.0


async def _read_voice_upload(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    boundary_match = re.search(r"boundary=([^;]+)", content_type)
    if "multipart/form-data" not in content_type or boundary_match is None:
        raise HTTPException(status_code=400, detail="请使用 multipart/form-data 上传 wav 文件。")

    body = await request.body()
    if len(body) > _voice_max_upload_bytes():
        raise HTTPException(status_code=413, detail="上传音频超过 VOICE_MAX_UPLOAD_MB 限制。")

    boundary = boundary_match.group(1).strip().strip('"').encode("utf-8")
    parts = body.split(b"--" + boundary)
    fields: dict[str, str] = {}
    file_bytes: bytes | None = None
    filename = ""

    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        raw_headers, raw_content = part.split(b"\r\n\r\n", 1)
        content = raw_content.rstrip(b"\r\n")
        headers = raw_headers.decode("utf-8", errors="ignore")
        name_match = re.search(r'name="([^"]+)"', headers)
        if name_match is None:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        if filename_match is not None:
            filename = Path(filename_match.group(1)).name
            file_bytes = content
        else:
            fields[name] = content.decode("utf-8", errors="ignore")

    if file_bytes is None or not filename:
        raise HTTPException(status_code=400, detail="缺少 file 字段。")
    if not filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="只允许上传 .wav 音频文件。")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="上传音频为空。")

    return {"file_bytes": file_bytes, "filename": filename, "fields": fields}


def _save_temp_wav(file_bytes: bytes) -> Path:
    with tempfile.NamedTemporaryFile(prefix="rk3588_voice_", suffix=".wav", delete=False) as temp_file:
        temp_file.write(file_bytes)
        return Path(temp_file.name)


def _validate_wav_duration(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            frame_rate = wav_file.getframerate()
            duration_s = frame_count / frame_rate if frame_rate else 0.0
    except wave.Error as exc:
        raise HTTPException(status_code=400, detail=f"无效 wav 音频：{exc}") from exc

    if duration_s <= 0:
        raise HTTPException(status_code=400, detail="空音频不会触发任务。")
    if duration_s > _voice_max_audio_seconds():
        raise HTTPException(status_code=400, detail="音频时长超过 VOICE_MAX_AUDIO_SECONDS 限制。")
    return round(duration_s, 3)


def _save_audio_command_log(
    result: VoiceAudioCommandResult,
    source: str,
    requested_by: str | None,
    filename: str,
    audio_duration_s: float | None,
) -> None:
    payload = {
        "audio_filename": filename,
        "audio_duration_s": audio_duration_s,
        "asr_backend": result.asr_backend,
        "recognized_text": result.recognized_text,
        "raw_text": result.raw_text,
        "intent": result.intent,
        "waypoint_id": result.waypoint_id,
        "need_confirm": result.need_confirm,
        "error": result.error,
        "asr_time_s": result.asr_time_s,
        "parser": result.parser,
        "llm_backend": result.llm_backend,
        "llm_model": result.llm_model,
        "pending_command_id": result.pending_command_id,
    }
    persistence.save_command_log(
        command="voice_audio_command",
        source=source,
        requested_by=requested_by,
        payload=payload,
        result=MissionActionResult(
            accepted=result.accepted,
            command=result.command or "voice_audio_command",
            task_status=result.task_status or state_store.get_current_task(),
            received_at=datetime.now(timezone.utc),
            detail=result.detail,
        ),
    )


def _voice_result_from_asr(
    asr_result: ASRResult,
    *,
    source: str,
    requested_by: str | None,
    use_llm: bool | None = None,
) -> tuple[VoiceAudioCommandResult, object | None]:
    if not asr_result.success or not asr_result.recognized_text.strip():
        return (
            VoiceAudioCommandResult(
                recognized_text=asr_result.recognized_text,
                raw_text=asr_result.raw_text,
                asr_backend=asr_result.backend,
                asr_time_s=asr_result.asr_time_s,
                model_load_time_s=asr_result.model_load_time_s,
                accepted=False,
                need_confirm=True,
                detail=asr_result.error or "ASR 未识别到有效文本，未触发任务。",
                error=asr_result.error or "empty-recognized-text",
            ),
            None,
        )

    text_request = VoiceTextCommandRequest(
        text=asr_result.recognized_text,
        source=source,
        requested_by=requested_by,
        use_llm=use_llm,
    )
    voice_result, state = voice_entry_service.handle_text_command(text_request)
    return (
        VoiceAudioCommandResult(
            recognized_text=asr_result.recognized_text,
            raw_text=asr_result.raw_text,
            asr_backend=asr_result.backend,
            asr_time_s=asr_result.asr_time_s,
            model_load_time_s=asr_result.model_load_time_s,
            intent=voice_result.intent,
            command=voice_result.command,
            payload=voice_result.payload,
            waypoint_id=voice_result.payload.get("waypoint_id") if voice_result.payload else None,
            accepted=voice_result.accepted,
            need_confirm=voice_result.need_confirm,
            detail=voice_result.detail,
            error=None if voice_result.accepted else voice_result.detail,
            task_status=voice_result.task_status,
            parser=voice_result.parser,
            llm_backend=voice_result.llm_backend,
            llm_model=voice_result.llm_model,
            llm_raw_output=voice_result.llm_raw_output,
            pending_command_id=voice_result.pending_command_id,
        ),
        state,
    )


def _smart_result_from_asr(
    asr_result: ASRResult,
    *,
    source: str,
    requested_by: str | None,
    use_llm: bool | None = None,
    generate_tts: bool = True,
) -> tuple[SmartCommandResult, object | None]:
    if not asr_result.success or not asr_result.recognized_text.strip():
        return (
            SmartCommandResult(
                request_id=f"smart_asr_{int(time.time() * 1000)}",
                recognized_text=asr_result.recognized_text,
                intent=None,
                data_source="asr",
                reply_text=asr_result.error or "ASR 未识别到有效文本，未触发任务。",
                need_confirm=False,
                error_reason=asr_result.error or "empty-recognized-text",
                confidence=0.0,
                parser="asr",
                timestamp=datetime.now(timezone.utc),
            ),
            None,
        )

    return smart_voice_service.handle(
        SmartCommandRequest(
            text=asr_result.recognized_text,
            source=source,
            requested_by=requested_by,
            use_llm=use_llm,
            generate_tts=generate_tts,
        )
    )


def _record_result_from_audio_result(
    audio_result: VoiceAudioCommandResult,
    *,
    audio_path: Path | None,
    duration: int,
    audio_device: str,
    audio_retained: bool,
) -> VoiceRecordCommandResult:
    return VoiceRecordCommandResult(
        **audio_result.model_dump(),
        audio_path=str(audio_path) if audio_path is not None and audio_retained else None,
        duration=duration,
        audio_device=audio_device,
        audio_retained=audio_retained,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/perception/latest_frame")
async def get_latest_perception_frame():
    return _latest_frame_response()


@app.head("/api/perception/latest_frame")
async def head_latest_perception_frame():
    return _latest_frame_response()


@app.get("/api/perception/frame_stream")
async def get_perception_frame_stream():
    return StreamingResponse(
        _mjpeg_frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Frame-Stream": "mjpeg",
        },
    )


@app.get("/api/state/latest", response_model=StateLatestResponse)
async def get_latest_state() -> StateLatestResponse:
    return StateLatestResponse(data=state_store.get_latest_state())


@app.get("/api/alerts", response_model=AlertsResponse)
async def get_alerts() -> AlertsResponse:
    return AlertsResponse(data=mock_state_service.get_alerts())


@app.get("/api/commands/logs", response_model=CommandLogsResponse)
async def get_command_logs() -> CommandLogsResponse:
    return CommandLogsResponse(data=mock_state_service.get_command_logs())


@app.get("/api/tasks/current", response_model=CurrentTaskResponse)
async def get_current_task() -> CurrentTaskResponse:
    return CurrentTaskResponse(data=state_store.get_current_task())


@app.get("/api/imu/latest", response_model=ImuLatestResponse)
async def get_latest_imu() -> ImuLatestResponse:
    return ImuLatestResponse(data=imu_store.get_latest())


@app.get("/api/external/weather/latest", response_model=ExternalWeatherLatestResponse)
async def get_latest_weather() -> ExternalWeatherLatestResponse:
    try:
        return ExternalWeatherLatestResponse(data=weather_provider.latest())
    except Exception as exc:
        return ExternalWeatherLatestResponse(
            success=False,
            error="weather_provider_failed",
            detail=f"天气数据读取失败：{type(exc).__name__}",
        )


@app.post("/api/voice/text_command", response_model=VoiceCommandResponse)
async def text_command(request: VoiceTextCommandRequest) -> VoiceCommandResponse:
    result, state = voice_entry_service.handle_text_command(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return VoiceCommandResponse(data=result)


@app.post("/api/voice/smart_command", response_model=SmartCommandResponse)
async def smart_command(request: SmartCommandRequest) -> SmartCommandResponse:
    result, state = smart_voice_service.handle(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return SmartCommandResponse(data=result)


@app.post("/api/voice/smart_audio_command", response_model=SmartCommandResponse)
async def smart_audio_command(request: Request) -> SmartCommandResponse:
    upload = await _read_voice_upload(request)
    temp_path: Path | None = None
    source = upload["fields"].get("source") or "smart-audio-upload"
    requested_by = upload["fields"].get("requested_by")
    use_llm = _parse_optional_bool(upload["fields"].get("use_llm"))
    generate_tts = _parse_optional_bool(upload["fields"].get("generate_tts"))
    if generate_tts is None:
        generate_tts = True

    try:
        temp_path = _save_temp_wav(upload["file_bytes"])
        _validate_wav_duration(temp_path)
        result, state = _smart_result_from_asr(
            asr_service.transcribe_audio_file(str(temp_path)),
            source=source,
            requested_by=requested_by,
            use_llm=use_llm,
            generate_tts=generate_tts,
        )
        if state is not None:
            await ws_manager.broadcast_state(state)
        return SmartCommandResponse(data=result)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@app.post("/api/voice/smart_record_command", response_model=SmartCommandResponse)
@app.post("/api/robot/voice/onboard_smart_command", response_model=SmartCommandResponse)
async def smart_record_command(request: VoiceRecordCommandRequest) -> SmartCommandResponse:
    duration = request.duration if request.duration is not None else audio_recorder.default_duration()
    keep_audio = request.keep_audio if request.keep_audio is not None else audio_recorder.default_keep_audio()
    source = request.source or "rk3588-smart-record-command"
    requested_by = request.requested_by
    record_result = audio_recorder.record(duration)

    if not record_result.success:
        if record_result.audio_path is not None and not keep_audio:
            record_result.audio_path.unlink(missing_ok=True)
        result = SmartCommandResult(
            request_id=f"smart_record_{int(time.time() * 1000)}",
            recognized_text="",
            intent=None,
            data_source="audio_recorder",
            reply_text=record_result.detail or "录音失败。",
            need_confirm=False,
            error_reason=record_result.error or "audio_record_failed",
            confidence=0.0,
            parser="recorder",
            timestamp=datetime.now(timezone.utc),
        )
        return SmartCommandResponse(success=False, data=result)

    audio_path = record_result.audio_path
    if audio_path is None:
        result = SmartCommandResult(
            request_id=f"smart_record_{int(time.time() * 1000)}",
            recognized_text="",
            intent=None,
            data_source="audio_recorder",
            reply_text="录音文件不存在。",
            need_confirm=False,
            error_reason="empty_audio_file",
            confidence=0.0,
            parser="recorder",
            timestamp=datetime.now(timezone.utc),
        )
        return SmartCommandResponse(success=False, data=result)

    result, state = _smart_result_from_asr(
        asr_service.transcribe_audio_file(str(audio_path)),
        source=source,
        requested_by=requested_by,
        use_llm=request.use_llm,
        generate_tts=True,
    )
    if state is not None:
        await ws_manager.broadcast_state(state)

    if not keep_audio:
        audio_path.unlink(missing_ok=True)

    return SmartCommandResponse(data=result)


@app.post("/api/voice/asr_text_mock", response_model=VoiceCommandResponse)
async def asr_text_mock(request: VoiceTextCommandRequest) -> VoiceCommandResponse:
    text_request = asr_service.transcribe_text_mock(request)
    result, state = voice_entry_service.handle_text_command(text_request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return VoiceCommandResponse(data=result)




@app.post("/api/voice/confirm_command", response_model=VoiceConfirmCommandResponse)
async def confirm_voice_command(request: VoiceConfirmCommandRequest) -> VoiceConfirmCommandResponse:
    result, state = voice_entry_service.confirm_pending_command(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return VoiceConfirmCommandResponse(data=result)


@app.post("/api/voice/speak", response_model=SpeakResponse)
async def speak(request: SpeakRequest) -> SpeakResponse:
    return SpeakResponse(data=tts_service.speak(request.text))


@app.get("/api/voice/tts/latest", response_model=TTSLatestResponse)
async def get_latest_tts() -> TTSLatestResponse:
    return TTSLatestResponse(data=tts_service.latest())


@app.get("/api/voice/tts/audio/{filename}")
async def get_tts_audio(filename: str):
    import re
    from app.services.tts_service import _tts_dir

    if not re.fullmatch(r"[a-zA-Z0-9_.\-]+", filename):
        raise HTTPException(status_code=400, detail="invalid filename")

    audio_path = _tts_dir() / filename
    if not audio_path.exists() or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="audio file not found")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_map = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "flac": "audio/flac"}
    media_type = media_map.get(ext, "application/octet-stream")

    return FileResponse(
        audio_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.post("/api/voice/audio_command", response_model=VoiceAudioCommandResponse)
async def audio_command(request: Request) -> VoiceAudioCommandResponse:
    upload = await _read_voice_upload(request)
    temp_path: Path | None = None
    source = upload["fields"].get("source") or "audio-upload"
    requested_by = upload["fields"].get("requested_by")
    use_llm = _parse_optional_bool(upload["fields"].get("use_llm"))
    audio_duration_s: float | None = None

    try:
        temp_path = _save_temp_wav(upload["file_bytes"])
        audio_duration_s = _validate_wav_duration(temp_path)
        result, state = _voice_result_from_asr(
            asr_service.transcribe_audio_file(str(temp_path)),
            source=source,
            requested_by=requested_by,
            use_llm=use_llm,
        )
        if state is not None:
            await ws_manager.broadcast_state(state)
        _save_audio_command_log(result, source, requested_by, upload["filename"], audio_duration_s)
        return VoiceAudioCommandResponse(data=result)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@app.post("/api/voice/record_command", response_model=VoiceRecordCommandResponse)
async def record_command(request: VoiceRecordCommandRequest) -> VoiceRecordCommandResponse:
    duration = request.duration if request.duration is not None else audio_recorder.default_duration()
    keep_audio = request.keep_audio if request.keep_audio is not None else audio_recorder.default_keep_audio()
    source = request.source or "rk3588-record-command"
    requested_by = request.requested_by
    record_result = audio_recorder.record(duration)

    if not record_result.success:
        if record_result.audio_path is not None and not keep_audio:
            record_result.audio_path.unlink(missing_ok=True)
        return VoiceRecordCommandResponse(
            success=False,
            error=record_result.error or "audio_record_failed",
            detail=record_result.detail or "录音失败。",
        )

    audio_path = record_result.audio_path
    if audio_path is None:
        return VoiceRecordCommandResponse(
            success=False,
            error="empty_audio_file",
            detail="录音文件不存在。",
        )

    result, state = _voice_result_from_asr(
        asr_service.transcribe_audio_file(str(audio_path)),
        source=source,
        requested_by=requested_by,
        use_llm=request.use_llm,
    )
    if state is not None:
        await ws_manager.broadcast_state(state)

    error_code = "asr_failed" if result.error and not result.recognized_text else result.error
    record_response = _record_result_from_audio_result(
        result.model_copy(update={"error": error_code}),
        audio_path=audio_path,
        duration=duration,
        audio_device=record_result.audio_device,
        audio_retained=keep_audio,
    )
    _save_audio_command_log(record_response, source, requested_by, audio_path.name, float(duration))

    if not keep_audio:
        audio_path.unlink(missing_ok=True)

    if result.error and not result.recognized_text:
        return VoiceRecordCommandResponse(
            success=False,
            data=record_response,
            error="asr_failed",
            detail=result.detail,
        )
    return VoiceRecordCommandResponse(data=record_response)


@app.post("/api/mission/go_to_waypoint", response_model=MissionActionResponse)
async def go_to_waypoint(request: GoToWaypointRequest) -> MissionActionResponse:
    result, state = mission_gateway.go_to_waypoint(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return MissionActionResponse(data=result)


@app.post("/api/mission/start_patrol", response_model=MissionActionResponse)
async def start_patrol(request: StartPatrolRequest) -> MissionActionResponse:
    result, state = mission_gateway.start_patrol(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return MissionActionResponse(data=result)


@app.post("/api/mission/pause", response_model=MissionActionResponse)
async def pause_mission(request: PauseMissionRequest) -> MissionActionResponse:
    result, state = mission_gateway.pause(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return MissionActionResponse(data=result)


@app.post("/api/mission/resume", response_model=MissionActionResponse)
async def resume_mission(request: ResumeMissionRequest) -> MissionActionResponse:
    result, state = mission_gateway.resume(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return MissionActionResponse(data=result)


@app.post("/api/mission/return_home", response_model=MissionActionResponse)
async def return_home(request: ReturnHomeRequest) -> MissionActionResponse:
    result, state = mission_gateway.return_home(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return MissionActionResponse(data=result)


@app.post("/api/system/mode/switch", response_model=ModeSwitchResponse)
async def switch_system_mode(request: ModeSwitchRequest) -> ModeSwitchResponse:
    response = ModeSwitchResponse(data=mock_state_service.switch_system_mode(request))
    latest_state = mode_manager.apply_mode_switch(
        response.data.system_mode,
        mock_state_service.get_latest_state(),
    )
    if response.data.system_mode.mode == "mock":
        imu_store.clear()
        await ws_manager.broadcast_imu(None)
    await ws_manager.broadcast_state(latest_state)
    return response


@app.post("/api/internal/perception/detection_status", response_model=PerceptionDetectionStatusResponse)
async def ingest_detection_status(
    request: PerceptionDetectionStatusRequest,
) -> PerceptionDetectionStatusResponse:
    latest_state = state_store.update_detection_status(request.detection_status)
    await ws_manager.broadcast_state(latest_state)
    return PerceptionDetectionStatusResponse(
        data=PerceptionDetectionStatusResult(
            accepted=True,
            state_updated=True,
            received_at=datetime.now(timezone.utc),
            detail="已接收本地视觉检测状态并刷新共享状态。",
        )
    )


@app.post("/api/internal/nuc/state", response_model=NucStateUpdateResponse)
async def ingest_nuc_state(request: NucStateUpdateRequest) -> NucStateUpdateResponse:
    result, latest_state = nuc_adapter.ingest_state_update(request)
    if latest_state is not None:
        await ws_manager.broadcast_state(mode_manager.record_real_state(latest_state))
    return NucStateUpdateResponse(data=result)


@app.post("/api/internal/nuc/imu", response_model=NucImuUpdateResponse)
async def ingest_nuc_imu(request: NucImuUpdateRequest) -> NucImuUpdateResponse:
    result, latest_imu = nuc_adapter.ingest_imu_update(request)
    if latest_imu is not None:
        await ws_manager.broadcast_imu(latest_imu)
    return NucImuUpdateResponse(data=result)


@app.post("/api/internal/navigation/map", response_model=NavigationUpdateResponse)
async def ingest_navigation_map(request: NavigationMapUpdateRequest) -> NavigationUpdateResponse:
    try:
        navigation_store.update_map(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return NavigationUpdateResponse(
        data=NavigationUpdateResult(
            updated_at=datetime.now(timezone.utc),
            detail="Navigation map cached.",
        )
    )


@app.post("/api/internal/navigation/state", response_model=NavigationUpdateResponse)
async def ingest_navigation_state(request: NavigationSnapshot) -> NavigationUpdateResponse:
    snapshot = navigation_store.update_snapshot(request)
    await ws_manager.broadcast_navigation(snapshot)
    return NavigationUpdateResponse(
        data=NavigationUpdateResult(
            updated_at=datetime.now(timezone.utc),
            detail="Navigation snapshot cached and broadcast.",
        )
    )


@app.get("/api/navigation/latest", response_model=NavigationLatestResponse)
async def navigation_latest() -> NavigationLatestResponse:
    return NavigationLatestResponse(data=navigation_store.latest())


@app.get("/api/navigation/map/metadata", response_model=NavigationMapMetadataResponse)
async def navigation_map_metadata() -> NavigationMapMetadataResponse:
    metadata = navigation_store.map_metadata()
    if metadata is None:
        raise HTTPException(status_code=404, detail="Navigation map is not available.")
    return NavigationMapMetadataResponse(data=metadata)


@app.get("/api/navigation/map/image")
async def navigation_map_image(request: Request) -> Response:
    map_result = navigation_store.map_png()
    if map_result is None:
        raise HTTPException(status_code=404, detail="Navigation map is not available.")
    metadata, png = map_result
    etag = f'"{metadata.version}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=60, must-revalidate"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=png, media_type="image/png", headers=headers)


@app.websocket("/ws/state")
async def state_stream(websocket: WebSocket) -> None:
    await ws_manager.connect(websocket, state_store.get_latest_state())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.websocket("/ws/imu")
async def imu_stream(websocket: WebSocket) -> None:
    await ws_manager.connect_imu(websocket, imu_store.get_latest())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.websocket("/ws/navigation")
async def navigation_stream(websocket: WebSocket) -> None:
    await ws_manager.connect_navigation(websocket, navigation_store.latest())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
