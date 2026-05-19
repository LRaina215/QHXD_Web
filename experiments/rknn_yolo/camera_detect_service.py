#!/usr/bin/env python3
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from detection_status_builder import build_detection_status
from infer_image import OUTPUT_LAYOUTS, RknnYoloRunner, draw_detections_on_array

SOURCE = "rk3588-rknn-yolo26"
EVENT_THROTTLE_SECONDS = {
    "person_detected": 5.0,
    "obstacle_detected": 5.0,
    "possible_blockage": 10.0,
}
JSON_OUTPUT_FD: int | None = None


class EventThrottler:
    def __init__(self, intervals: dict[str, float]) -> None:
        self.intervals = intervals
        self.last_emit: dict[str, float] = {}

    def filter(self, events: list[dict[str, str]], now: float) -> list[dict[str, str]]:
        kept: list[dict[str, str]] = []
        for event in events:
            event_type = event.get("event_type", "")
            interval = self.intervals.get(event_type, 0.0)
            last_seen = self.last_emit.get(event_type)
            if interval > 0.0 and last_seen is not None and now - last_seen < interval:
                continue
            self.last_emit[event_type] = now
            kept.append(event)
        return kept


class CameraSource:
    color_order = "bgr"

    def read(self) -> tuple[bool, Any]:
        raise NotImplementedError

    def release(self) -> None:
        pass


class OpenCvCameraSource(CameraSource):
    color_order = "bgr"

    def __init__(self, cv2_module, source: int | str) -> None:
        self._cap = cv2_module.VideoCapture(source)

    def is_opened(self) -> bool:
        return bool(self._cap.isOpened())

    def read(self) -> tuple[bool, Any]:
        return self._cap.read()

    def release(self) -> None:
        self._cap.release()


class FfmpegCameraSource(CameraSource):
    color_order = "rgb"

    def __init__(self, device: str) -> None:
        self.device = device

    def is_opened(self) -> bool:
        return Path(self.device).exists() and shutil.which("ffmpeg") is not None

    def read(self) -> tuple[bool, Any]:
        try:
            from PIL import Image
            import numpy as np
        except ImportError as exc:
            print(f"ffmpeg camera fallback requires Pillow and numpy: {exc}", file=sys.stderr)
            return False, None

        command = [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "video4linux2",
            "-i",
            self.device,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
        try:
            completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        except Exception as exc:
            print(f"ffmpeg camera read failed: {exc}", file=sys.stderr)
            return False, None
        if completed.returncode != 0 or not completed.stdout:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            if message:
                print(f"ffmpeg camera read failed: {message}", file=sys.stderr)
            return False, None
        try:
            image = Image.open(io.BytesIO(completed.stdout)).convert("RGB")
            return True, np.asarray(image)
        except Exception as exc:
            print(f"ffmpeg camera frame decode failed: {exc}", file=sys.stderr)
            return False, None

    def release(self) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run continuous RKNN YOLO detection from a USB camera.")
    parser.add_argument("--model", required=True, help="Path to a .rknn model file.")
    parser.add_argument("--labels", required=True, help="Path to a labels.txt file.")
    parser.add_argument("--camera", default="0", help="OpenCV camera index or device path, default 0.")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold.")
    parser.add_argument("--fps", type=float, default=2.0, help="Detection FPS, default 2.")
    parser.add_argument("--frame-id", default="camera_front", help="Frame ID for detection_status output.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend base URL.")
    parser.add_argument("--submit", action="store_true", help="Submit detection_status to backend.")
    parser.add_argument("--save-latest", default=None, help="Optional path to save latest detection image.")
    parser.add_argument("--max-det", type=int, default=20, help="Maximum detections kept after NMS.")
    parser.add_argument("--dry-run", action="store_true", help="Print detection_status JSON and do not submit.")
    parser.add_argument("--output-layout", choices=OUTPUT_LAYOUTS, default="xyxy_score_class", help="6-column RKNN output layout.")
    parser.add_argument("--submit-interval", type=float, default=0.0, help="Minimum seconds between backend submissions. Default follows FPS.")
    parser.add_argument("--read-fail-limit", type=int, default=5, help="Consecutive frame read failures before reporting camera offline.")
    parser.add_argument("--max-frames", type=int, default=0, help="Optional validation limit. 0 means run until Ctrl+C.")
    args = parser.parse_args()
    if args.dry_run:
        _redirect_stdout_to_stderr_for_jsonl()

    try:
        return run_service(args)
    except KeyboardInterrupt:
        print("Camera detection service interrupted by user.", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"Camera detection service failed: {exc}", file=sys.stderr)
        return 2


def run_service(args: argparse.Namespace) -> int:
    camera = _open_camera(args.camera)
    runner: RknnYoloRunner | None = None
    final_status: dict[str, Any] | None = None
    final_status_submitted = False

    try:
        if camera is None:
            status = _service_status(args, False, "camera_unavailable", "warning", "摄像头不可用或无法打开")
            _emit_status(status, dry_run=args.dry_run)
            _maybe_submit(args, status, force=True)
            return 2

        runner = RknnYoloRunner(
            args.model,
            args.labels,
            conf=args.conf,
            output_layout=args.output_layout,
            max_det=args.max_det,
            frame_id=args.frame_id,
            source=SOURCE,
        ).load()

        throttler = EventThrottler(EVENT_THROTTLE_SECONDS)
        frame_interval = 1.0 / max(args.fps, 0.1)
        submit_interval = args.submit_interval if args.submit_interval > 0 else frame_interval
        last_submit_at = 0.0
        frame_count = 0
        read_failures = 0

        print(
            f"Camera detection service started: camera={args.camera}, backend={camera.__class__.__name__}, "
            f"fps={args.fps}, submit={args.submit and not args.dry_run}, dry_run={args.dry_run}",
            file=sys.stderr,
        )

        while True:
            loop_started = time.monotonic()
            ok, frame = camera.read()
            if not ok or frame is None:
                read_failures += 1
                print(f"Camera frame read failed ({read_failures}/{args.read_fail_limit}).", file=sys.stderr)
                if read_failures >= max(1, args.read_fail_limit):
                    status = _service_status(args, False, "camera_read_failed", "warning", "摄像头连续读取失败，检测服务离线")
                    _emit_status(status, dry_run=args.dry_run)
                    _maybe_submit(args, status, force=True)
                    final_status = status
                    final_status_submitted = args.submit and not args.dry_run
                    return 3
                _sleep_until_next(loop_started, frame_interval)
                continue

            read_failures = 0
            try:
                objects = runner.infer_frame(frame, color_order=camera.color_order)
                status = runner.build_status(objects, timestamp=_utc_now())
                status["events"] = throttler.filter(status.get("events", []), time.monotonic())
            except Exception as exc:
                status = _service_status(args, False, "yolo_inference_error", "error", f"YOLO 推理失败：{exc}")
                print(status["events"][0]["message"], file=sys.stderr)

            if args.save_latest:
                try:
                    draw_detections_on_array(frame, Path(args.save_latest), status.get("objects", []), color_order=camera.color_order)
                except Exception as exc:
                    print(f"Save latest detection image failed: {exc}", file=sys.stderr)

            _emit_status(status, dry_run=args.dry_run)
            now = time.monotonic()
            if args.submit and not args.dry_run and now - last_submit_at >= submit_interval:
                _submit_status(args.backend_url, status)
                last_submit_at = now

            frame_count += 1
            if args.max_frames > 0 and frame_count >= args.max_frames:
                final_status = _service_status(args, False, "service_stopped", "info", "摄像头检测服务已按 max-frames 结束")
                return 0

            _sleep_until_next(loop_started, frame_interval)
    except KeyboardInterrupt:
        final_status = _service_status(args, False, "service_stopped", "info", "摄像头检测服务已停止")
        _emit_status(final_status, dry_run=args.dry_run)
        _maybe_submit(args, final_status, force=True)
        final_status_submitted = args.submit and not args.dry_run
        return 0
    finally:
        if final_status is not None and args.submit and not args.dry_run and not final_status_submitted:
            _submit_status(args.backend_url, final_status)
        if runner is not None:
            runner.release()
        if camera is not None:
            camera.release()
        print("Camera and RKNN runtime released.", file=sys.stderr)


def _open_camera(camera_arg: str) -> CameraSource | None:
    source = _parse_camera_source(camera_arg)
    try:
        import cv2
    except ImportError:
        cv2 = None

    if cv2 is not None:
        camera = OpenCvCameraSource(cv2, source)
        if camera.is_opened():
            return camera
        camera.release()
        print(f"OpenCV could not open camera {camera_arg}; trying ffmpeg fallback.", file=sys.stderr)
    else:
        print("OpenCV is not installed; trying ffmpeg camera fallback.", file=sys.stderr)

    device = _camera_arg_to_device(camera_arg)
    camera = FfmpegCameraSource(device)
    if camera.is_opened():
        return camera
    print(f"ffmpeg fallback could not open {device}.", file=sys.stderr)
    return None


def _parse_camera_source(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def _camera_arg_to_device(value: str) -> str:
    if value.startswith("/dev/"):
        return value
    if value.isdigit():
        return f"/dev/video{value}"
    return value


def _service_status(args: argparse.Namespace, enabled: bool, event_type: str, level: str, message: str) -> dict[str, Any]:
    status = build_detection_status(
        [],
        model_name=Path(args.model).name,
        frame_id=args.frame_id,
        source=SOURCE,
        enabled=enabled,
        timestamp=_utc_now(),
    )
    status["events"] = [{"event_type": event_type, "level": level, "message": message}]
    return status


def _emit_status(status: dict[str, Any], *, dry_run: bool) -> None:
    objects = status.get("objects", [])
    events = status.get("events", [])
    top = "none"
    if objects:
        first = objects[0]
        top = f"{first.get('class_name', 'unknown')}:{float(first.get('confidence', 0.0)):.2f}"
    event_types = ",".join(event.get("event_type", "unknown") for event in events) or "none"
    print(
        f"[{status.get('timestamp')}] enabled={status.get('enabled')} objects={len(objects)} top={top} events={event_types}",
        file=sys.stderr,
    )
    if dry_run:
        _write_jsonl({"detection_status": status})


def _redirect_stdout_to_stderr_for_jsonl() -> None:
    global JSON_OUTPUT_FD
    if JSON_OUTPUT_FD is not None:
        return
    sys.stdout.flush()
    JSON_OUTPUT_FD = os.dup(1)
    os.dup2(2, 1)


def _write_jsonl(payload: dict[str, Any]) -> None:
    if JSON_OUTPUT_FD is None:
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    os.write(JSON_OUTPUT_FD, data)


def _maybe_submit(args: argparse.Namespace, status: dict[str, Any], *, force: bool = False) -> None:
    if args.submit and not args.dry_run:
        _submit_status(args.backend_url, status)
    elif force and args.submit and args.dry_run:
        print("Dry-run enabled; detection_status was not submitted.", file=sys.stderr)


def _submit_status(backend_url: str, status: dict[str, Any]) -> bool:
    url = backend_url.rstrip("/") + "/api/internal/perception/detection_status"
    data = json.dumps({"detection_status": status}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = response.status
        print(f"Submitted detection_status: HTTP {status_code} {body[:160]}", file=sys.stderr)
        return 200 <= status_code < 300
    except urllib.error.URLError as exc:
        print(f"Submit detection_status failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"Submit detection_status failed: {exc}", file=sys.stderr)
    return False


def _sleep_until_next(loop_started: float, frame_interval: float) -> None:
    elapsed = time.monotonic() - loop_started
    delay = max(0.0, frame_interval - elapsed)
    if delay > 0:
        time.sleep(delay)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
