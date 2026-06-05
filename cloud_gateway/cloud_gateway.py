import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import time
import wave
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque

import httpx
import websockets
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse


SERVICE_NAME = "lingxun-cloud-gateway"
RK_BACKEND_BASE_URL = os.getenv("RK_BACKEND_BASE_URL", "http://100.113.173.115:8000").rstrip("/")
PUBLIC_API_TOKEN = os.getenv("PUBLIC_API_TOKEN", "")
PUBLIC_CONTROL_ENABLED = os.getenv("PUBLIC_CONTROL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
PUBLIC_RATE_LIMIT_PER_MINUTE = int(os.getenv("PUBLIC_RATE_LIMIT_PER_MINUTE", "60"))
PUBLIC_AUDIO_MAX_MB = float(os.getenv("PUBLIC_AUDIO_MAX_MB", "20"))
PUBLIC_BROWSER_AUDIO_MAX_MB = float(os.getenv("PUBLIC_BROWSER_AUDIO_MAX_MB", "5"))
PUBLIC_BROWSER_AUDIO_MAX_SECONDS = float(os.getenv("PUBLIC_BROWSER_AUDIO_MAX_SECONDS", "10"))
GATEWAY_AUDIO_TMP_DIR = Path(os.getenv("GATEWAY_AUDIO_TMP_DIR", "/tmp/lingxun-cloud-gateway-audio"))
GATEWAY_AUDIO_KEEP_DIR = Path(os.getenv("GATEWAY_AUDIO_KEEP_DIR", "/var/log/lingxun-cloud-gateway/audio_records"))
GATEWAY_AUDIO_KEEP_MAX_FILES = int(os.getenv("GATEWAY_AUDIO_KEEP_MAX_FILES", "20"))
ROBOT_STATE_TIMEOUT_SECONDS = float(os.getenv("ROBOT_STATE_TIMEOUT_SECONDS", "3"))
FORWARD_TIMEOUT_SECONDS = float(os.getenv("FORWARD_TIMEOUT_SECONDS", "30"))
STREAM_TIMEOUT_SECONDS = float(os.getenv("STREAM_TIMEOUT_SECONDS", "300"))
LOG_PATH = Path(os.getenv("GATEWAY_OPERATION_LOG", "/var/log/lingxun-cloud-gateway/operations.jsonl"))
PUBLIC_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "PUBLIC_CORS_ORIGINS",
        "https://lingxunrobot.cn,https://www.lingxunrobot.cn",
    ).split(",")
    if origin.strip()
]

BLOCKED_PUBLIC_PATHS = {
    "/api/voice/record_command",
}

WRITE_PATH_PREFIXES = (
    "/api/voice/text_command",
    "/api/voice/audio_command",
    "/api/voice/browser_audio_command",
    "/api/voice/browser_smart_command",
    "/api/voice/smart_command",
    "/api/voice/smart_audio_command",
    "/api/voice/speak",
    "/api/voice/confirm_command",
    "/api/robot/voice/onboard_record_command",
    "/api/robot/voice/onboard_smart_command",
    "/api/mission/",
    "/api/system/mode/switch",
)

CONTROL_PATH_PREFIXES = (
    "/api/mission/",
)

ALLOWED_PATH_PREFIXES = (
    "/health",
    "/api/state/latest",
    "/api/alerts",
    "/api/commands/logs",
    "/api/tasks/current",
    "/api/imu/latest",
    "/api/perception/latest_frame",
    "/api/perception/frame_stream",
    "/api/external/weather/latest",
    "/api/voice/text_command",
    "/api/voice/audio_command",
    "/api/voice/browser_audio_command",
    "/api/voice/browser_smart_command",
    "/api/voice/smart_command",
    "/api/voice/smart_audio_command",
    "/api/voice/speak",
    "/api/voice/tts/latest",
    "/api/voice/confirm_command",
    "/api/robot/voice/onboard_record_command",
    "/api/robot/voice/onboard_smart_command",
    "/api/mission/",
    "/api/system/mode/switch",
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

app = FastAPI(title="Lingxun Cloud Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=PUBLIC_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)
rate_buckets: dict[str, Deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _is_allowed_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


def _is_write_path(path: str, method: str) -> bool:
    return method.upper() not in {"GET", "HEAD", "OPTIONS"} or any(path.startswith(prefix) for prefix in WRITE_PATH_PREFIXES)


def _is_control_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in CONTROL_PATH_PREFIXES)


def _operation_log(event: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _reject(status_code: int, detail: str, request: Request | None = None, request_id: str | None = None) -> JSONResponse:
    if request is not None:
        _operation_log(
            {
                "timestamp": time.time(),
                "request_id": request_id,
                "client_ip": _client_ip(request),
                "method": request.method,
                "path": request.url.path,
                "accepted": False,
                "reject_reason": detail,
            }
        )
    return JSONResponse(status_code=status_code, content={"success": False, "error": detail, "request_id": request_id})


def _auth_ok(request: Request) -> bool:
    if not PUBLIC_API_TOKEN:
        return False
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {PUBLIC_API_TOKEN}"


def _check_rate_limit(request: Request) -> bool:
    if PUBLIC_RATE_LIMIT_PER_MINUTE <= 0:
        return True
    now = time.time()
    key = _client_ip(request)
    bucket = rate_buckets[key]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= PUBLIC_RATE_LIMIT_PER_MINUTE:
        return False
    bucket.append(now)
    return True


def _forward_headers(request: Request, request_id: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "authorization"
    }
    headers["x-cloud-gateway"] = SERVICE_NAME
    headers["x-request-id"] = request_id
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto", "https")
    return headers


def _response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _validate_browser_audio_upload(file: UploadFile, data: bytes) -> JSONResponse | None:
    allowed_mimes = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave"}
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    if content_type not in allowed_mimes:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "unsupported_audio_type", "detail": f"不支持的音频类型：{file.content_type}"},
        )
    if not data:
        return JSONResponse(status_code=400, content={"success": False, "error": "empty_audio", "detail": "上传音频为空。"})
    if len(data) > int(PUBLIC_BROWSER_AUDIO_MAX_MB * 1024 * 1024):
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": "browser_audio_too_large", "detail": "浏览器录音超过大小限制。"},
        )
    return None


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            return frame_count / frame_rate if frame_rate else 0.0
    except wave.Error:
        return 0.0


def _cleanup_kept_audio() -> None:
    if GATEWAY_AUDIO_KEEP_MAX_FILES <= 0 or not GATEWAY_AUDIO_KEEP_DIR.exists():
        return
    files = sorted(
        [path for path in GATEWAY_AUDIO_KEEP_DIR.iterdir() if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in files[GATEWAY_AUDIO_KEEP_MAX_FILES:]:
        with contextlib.suppress(Exception):
            stale.unlink()


async def _forward_wav_to_rk(
    wav_path: Path,
    *,
    source: str,
    requested_by: str | None,
    keep_audio: bool,
    request_id: str,
    rk_path: str = "/api/voice/audio_command",
) -> httpx.Response:
    fields = {
        "source": source,
        "requested_by": requested_by or "",
        "keep_audio": "true" if keep_audio else "false",
    }
    async with httpx.AsyncClient(timeout=FORWARD_TIMEOUT_SECONDS, trust_env=False) as client:
        with wav_path.open("rb") as handle:
            files = {
                "file": ("browser_audio.wav", handle, "audio/wav"),
            }
            return await client.post(
                f"{RK_BACKEND_BASE_URL}{rk_path}",
                data=fields,
                files=files,
                headers={"x-cloud-gateway": SERVICE_NAME, "x-request-id": request_id},
            )


async def _forward_json_to_rk(path: str, payload: dict, request_id: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=FORWARD_TIMEOUT_SECONDS, trust_env=False) as client:
        return await client.post(
            f"{RK_BACKEND_BASE_URL}{path}",
            json=payload,
            headers={"x-cloud-gateway": SERVICE_NAME, "x-request-id": request_id},
        )


async def _robot_state() -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=ROBOT_STATE_TIMEOUT_SECONDS, trust_env=False) as client:
            response = await client.get(f"{RK_BACKEND_BASE_URL}/api/state/latest")
            response.raise_for_status()
            payload = response.json()
            return payload.get("data")
    except Exception:
        return None


async def _ensure_control_allowed(request: Request, request_id: str) -> JSONResponse | None:
    if not PUBLIC_CONTROL_ENABLED:
        return _reject(403, "public_control_disabled", request, request_id)

    state = await _robot_state()
    if state is None:
        return _reject(503, "robot_offline", request, request_id)

    device_status = state.get("device_status") or {}
    if not device_status.get("online", False):
        return _reject(503, "robot_offline", request, request_id)
    if device_status.get("emergency_stop", False):
        return _reject(423, "robot_emergency_stop", request, request_id)
    if device_status.get("fault_code"):
        return _reject(423, f"robot_fault:{device_status.get('fault_code')}", request, request_id)
    return None


async def _preflight(request: Request, request_id: str) -> JSONResponse | None:
    path = request.url.path
    method = request.method.upper()

    if path in BLOCKED_PUBLIC_PATHS:
        return _reject(403, "public_endpoint_disabled", request, request_id)

    if not _is_allowed_path(path):
        return _reject(404, "not_in_public_whitelist", request, request_id)

    if _is_write_path(path, method):
        if not _check_rate_limit(request):
            return _reject(429, "rate_limited", request, request_id)
        if not _auth_ok(request):
            return _reject(401, "unauthorized", request, request_id)

    if path == "/api/voice/audio_command":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > int(PUBLIC_AUDIO_MAX_MB * 1024 * 1024):
            return _reject(413, "audio_upload_too_large", request, request_id)

    if _is_control_path(path):
        control_reject = await _ensure_control_allowed(request, request_id)
        if control_reject is not None:
            return control_reject

    return None


@app.get("/health")
async def health() -> dict:
    state = await _robot_state()
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "rk_backend_base_url": RK_BACKEND_BASE_URL,
        "rk_online": state is not None,
        "public_control_enabled": PUBLIC_CONTROL_ENABLED,
    }


@app.post("/api/voice/browser_audio_command")
@app.post("/api/voice/browser_smart_command")
async def browser_audio_command(
    request: Request,
    file: UploadFile = File(...),
    source: str = Form("browser-mic"),
    requested_by: str | None = Form("operator"),
    keep_audio: str | bool | None = Form(False),
    smart: str | bool | None = Form(False),
):
    request_id = str(uuid.uuid4())
    if not _check_rate_limit(request):
        return _reject(429, "rate_limited", request, request_id)
    if not _auth_ok(request):
        return _reject(401, "unauthorized", request, request_id)

    state = await _robot_state()
    if state is None:
        return _reject(503, "robot_offline", request, request_id)

    raw_audio = await file.read()
    invalid = _validate_browser_audio_upload(file, raw_audio)
    if invalid is not None:
        return invalid

    if shutil.which("ffmpeg") is None:
        return _reject(500, "ffmpeg_not_installed", request, request_id)

    keep = _parse_bool(keep_audio, False)
    GATEWAY_AUDIO_TMP_DIR.mkdir(parents=True, exist_ok=True)
    input_suffix = Path(file.filename or "browser_audio.webm").suffix or ".webm"
    input_path = GATEWAY_AUDIO_TMP_DIR / f"{request_id}{input_suffix}"
    wav_path = GATEWAY_AUDIO_TMP_DIR / f"{request_id}.wav"
    input_path.write_bytes(raw_audio)

    try:
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(wav_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "ffmpeg_transcode_failed",
                    "detail": result.stderr.strip() or "浏览器录音转码失败。",
                    "request_id": request_id,
                },
            )

        duration_s = _wav_duration_seconds(wav_path)
        if duration_s <= 0:
            return JSONResponse(status_code=400, content={"success": False, "error": "invalid_audio_duration", "request_id": request_id})
        if duration_s > PUBLIC_BROWSER_AUDIO_MAX_SECONDS:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "browser_audio_too_long", "duration_s": round(duration_s, 3), "request_id": request_id},
            )

        use_smart = request.url.path.endswith("/browser_smart_command") or _parse_bool(smart, False)
        upstream_response = await _forward_wav_to_rk(
            wav_path,
            source=source or "browser-mic",
            requested_by=requested_by,
            keep_audio=keep,
            request_id=request_id,
            rk_path="/api/voice/smart_audio_command" if use_smart else "/api/voice/audio_command",
        )

        if keep:
            GATEWAY_AUDIO_KEEP_DIR.mkdir(parents=True, exist_ok=True)
            kept_base = GATEWAY_AUDIO_KEEP_DIR / request_id
            shutil.copy2(input_path, kept_base.with_suffix(input_suffix))
            shutil.copy2(wav_path, kept_base.with_suffix(".wav"))
            _cleanup_kept_audio()

        _operation_log(
            {
                "timestamp": time.time(),
                "request_id": request_id,
                "client_ip": _client_ip(request),
                "method": request.method,
                "path": request.url.path,
                "accepted": True,
                "forward_status": upstream_response.status_code,
                "duration_s": round(duration_s, 3),
                "source": source,
            }
        )
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=_response_headers(upstream_response.headers),
            media_type=upstream_response.headers.get("content-type"),
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=400, content={"success": False, "error": "ffmpeg_timeout", "request_id": request_id})
    except Exception as exc:
        return _reject(503, f"browser_audio_forward_failed:{exc.__class__.__name__}", request, request_id)
    finally:
        if not keep:
            with contextlib.suppress(Exception):
                input_path.unlink()
            with contextlib.suppress(Exception):
                wav_path.unlink()


@app.post("/api/robot/voice/onboard_record_command")
@app.post("/api/robot/voice/onboard_smart_command")
async def onboard_record_command(request: Request):
    request_id = str(uuid.uuid4())
    if not _check_rate_limit(request):
        return _reject(429, "rate_limited", request, request_id)
    if not _auth_ok(request):
        return _reject(401, "unauthorized", request, request_id)

    state = await _robot_state()
    if state is None:
        return _reject(503, "robot_offline", request, request_id)

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        duration = int(payload.get("duration", 3))
    except (TypeError, ValueError):
        duration = 3
    payload["duration"] = min(max(duration, 1), int(PUBLIC_BROWSER_AUDIO_MAX_SECONDS))
    payload["source"] = payload.get("source") or "web-onboard-mic"
    payload["requested_by"] = payload.get("requested_by") or "operator"
    payload["keep_audio"] = bool(payload.get("keep_audio", True))
    smart_flag = payload.pop("smart", None)
    use_smart = request.url.path.endswith("/onboard_smart_command") or _parse_bool(smart_flag, False)

    try:
        upstream_response = await _forward_json_to_rk(
            "/api/voice/smart_record_command" if use_smart else "/api/voice/record_command",
            payload,
            request_id,
        )
    except Exception as exc:
        return _reject(503, f"onboard_record_forward_failed:{exc.__class__.__name__}", request, request_id)

    _operation_log(
        {
            "timestamp": time.time(),
            "request_id": request_id,
            "client_ip": _client_ip(request),
            "method": request.method,
            "path": request.url.path,
            "accepted": True,
            "forward_status": upstream_response.status_code,
            "source": payload["source"],
            "public_control_enabled": PUBLIC_CONTROL_ENABLED,
        }
    )
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=_response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_http(path: str, request: Request):
    request_id = str(uuid.uuid4())
    url_path = request.url.path

    reject = await _preflight(request, request_id)
    if reject is not None:
        return reject

    if request.method.upper() == "OPTIONS":
        return Response(status_code=204)

    upstream_url = f"{RK_BACKEND_BASE_URL}{url_path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    headers = _forward_headers(request, request_id)
    body = await request.body()

    timeout = STREAM_TIMEOUT_SECONDS if url_path == "/api/perception/frame_stream" else FORWARD_TIMEOUT_SECONDS

    if url_path == "/api/perception/frame_stream":
        client = httpx.AsyncClient(timeout=timeout, trust_env=False)
        upstream_request = client.build_request(request.method, upstream_url, headers=headers, content=body)
        try:
            upstream_response = await client.send(upstream_request, stream=True)
        except Exception as exc:
            await client.aclose()
            return _reject(503, f"rk_forward_failed:{exc.__class__.__name__}", request, request_id)

        async def body_iter():
            try:
                async for chunk in upstream_response.aiter_bytes():
                    yield chunk
            finally:
                await upstream_response.aclose()
                await client.aclose()

        _operation_log(
            {
                "timestamp": time.time(),
                "request_id": request_id,
                "client_ip": _client_ip(request),
                "method": request.method,
                "path": url_path,
                "accepted": True,
                "forward_status": upstream_response.status_code,
            }
        )
        return StreamingResponse(
            body_iter(),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type"),
            headers=_response_headers(upstream_response.headers),
        )

    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            upstream_response = await client.request(request.method, upstream_url, headers=headers, content=body)
    except Exception as exc:
        return _reject(503, f"rk_forward_failed:{exc.__class__.__name__}", request, request_id)

    _operation_log(
        {
            "timestamp": time.time(),
            "request_id": request_id,
            "client_ip": _client_ip(request),
            "method": request.method,
            "path": url_path,
            "accepted": True,
            "forward_status": upstream_response.status_code,
        }
    )
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=_response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )


@app.websocket("/ws/{channel}")
async def proxy_ws(websocket: WebSocket, channel: str):
    if channel not in {"state", "imu"}:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    scheme = "wss" if RK_BACKEND_BASE_URL.startswith("https://") else "ws"
    upstream_base = RK_BACKEND_BASE_URL.replace("https://", "").replace("http://", "")
    upstream_url = f"{scheme}://{upstream_base}/ws/{channel}"

    try:
        async with websockets.connect(upstream_url, open_timeout=5, ping_interval=20, ping_timeout=20) as upstream:
            async def browser_to_upstream():
                try:
                    while True:
                        message = await websocket.receive()
                        if "text" in message and message["text"] is not None:
                            await upstream.send(message["text"])
                        elif "bytes" in message and message["bytes"] is not None:
                            await upstream.send(message["bytes"])
                except WebSocketDisconnect:
                    await upstream.close()

            async def upstream_to_browser():
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            await asyncio.gather(browser_to_upstream(), upstream_to_browser())
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
