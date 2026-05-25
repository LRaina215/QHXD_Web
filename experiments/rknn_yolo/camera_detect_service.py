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

from detection_status_builder import OBSTACLE_CLASSES, build_detection_status
from infer_image import OUTPUT_LAYOUTS, RknnYoloRunner, draw_detections_on_array

SOURCE = "rk3588-rknn-yolo26"
EVENT_THROTTLE_SECONDS = {
    "person_detected": 5.0,
    "obstacle_detected": 5.0,
    "possible_blockage": 10.0,
}
JSON_OUTPUT_FD: int | None = None
CONFIG_FIELDS = {
    "model",
    "labels",
    "camera",
    "hik_timeout_ms",
    "hik_serial",
    "hik_index",
    "camera_backend",
    "camera_retry_interval",
    "hik_params",
    "conf",
    "fps",
    "frame_id",
    "backend_url",
    "submit",
    "save_latest",
    "max_det",
    "dry_run",
    "output_layout",
    "submit_interval",
    "read_fail_limit",
    "max_frames",
    "save_debug_frames",
    "debug_frame_dir",
    "debug_every_n",
    "hold_seconds",
    "hold_classes",
    "event_min_confidence",
    "event_min_area_ratio",
    "blockage_frames_required",
    "person_event_interval",
    "obstacle_event_interval",
    "blockage_event_interval",
}
DEFAULT_OPTIONS: dict[str, Any] = {
    "model": None,
    "labels": None,
    "camera": "0",
    "hik_timeout_ms": 1000,
    "hik_serial": None,
    "hik_index": 0,
    "camera_backend": "auto",
    "camera_retry_interval": 0.0,
    "hik_params": {},
    "conf": 0.25,
    "fps": 2.0,
    "frame_id": "camera_front",
    "backend_url": "http://127.0.0.1:8000",
    "submit": False,
    "save_latest": "outputs/latest_camera_detection.jpg",
    "max_det": 20,
    "dry_run": False,
    "output_layout": "xyxy_score_class",
    "submit_interval": 0.0,
    "read_fail_limit": 5,
    "max_frames": 0,
    "save_debug_frames": False,
    "debug_frame_dir": "outputs/debug_frames",
    "debug_every_n": 1,
    "hold_seconds": 2.0,
    "hold_classes": ["person", "obstacle"],
    "event_min_confidence": 0.25,
    "event_min_area_ratio": 0.001,
    "blockage_frames_required": 3,
    "person_event_interval": EVENT_THROTTLE_SECONDS["person_detected"],
    "obstacle_event_interval": EVENT_THROTTLE_SECONDS["obstacle_detected"],
    "blockage_event_interval": EVENT_THROTTLE_SECONDS["possible_blockage"],
}


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


class RecentDetectionHold:
    def __init__(self, duration_s: float, hold_classes: set[str]) -> None:
        self.duration_s = max(0.0, duration_s)
        self.hold_classes = hold_classes
        self._cache: dict[str, dict[str, Any]] = {}

    def update(self, objects: list[dict[str, Any]], *, timestamp: str, now: float) -> list[dict[str, Any]]:
        current_objects: list[dict[str, Any]] = []
        current_hold_keys: set[str] = set()
        for item in objects:
            annotated = dict(item)
            annotated["current_frame"] = True
            annotated["recently_seen"] = False
            annotated["last_seen_at"] = timestamp
            annotated["age_s"] = 0.0
            current_objects.append(annotated)
            hold_key = self._hold_key(item)
            if hold_key is None:
                continue
            current_hold_keys.add(hold_key)
            cached = dict(annotated)
            cached["last_seen_monotonic"] = now
            self._cache[hold_key] = cached

        if self.duration_s <= 0:
            self._cache = {key: value for key, value in self._cache.items() if key in current_hold_keys}
            return current_objects

        recent_objects: list[dict[str, Any]] = []
        expired_keys: list[str] = []
        for key, cached in self._cache.items():
            age_s = now - float(cached.get("last_seen_monotonic", now))
            if age_s > self.duration_s:
                expired_keys.append(key)
                continue
            if key in current_hold_keys:
                continue
            recent = {name: value for name, value in cached.items() if name != "last_seen_monotonic"}
            recent["current_frame"] = False
            recent["recently_seen"] = True
            recent["age_s"] = round(age_s, 3)
            recent_objects.append(recent)
        for key in expired_keys:
            self._cache.pop(key, None)
        return current_objects + recent_objects

    def _hold_key(self, item: dict[str, Any]) -> str | None:
        class_name = str(item.get("class_name", ""))
        if class_name in self.hold_classes:
            return class_name
        if "obstacle" in self.hold_classes and class_name in OBSTACLE_CLASSES:
            return f"obstacle:{class_name}"
        return None


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
    parser.add_argument("--config", default=None, help="Optional JSON config file. CLI values override config values.")
    parser.add_argument("--model", default=None, help="Path to a .rknn model file.")
    parser.add_argument("--labels", default=None, help="Path to a labels.txt file.")
    parser.add_argument("--camera", default=None, help="OpenCV camera index or device path, default 0.")
    parser.add_argument("--camera-backend", choices=["auto", "usb", "hik"], default=None, help="Camera source backend. auto/usb use OpenCV+ffmpeg; hik uses Hikrobot MVS SDK.")
    parser.add_argument("--hik-index", type=int, default=None, help="Hik SDK camera index after optional serial filtering.")
    parser.add_argument("--hik-serial", default=None, help="Optional Hik camera serial filter.")
    parser.add_argument("--hik-timeout-ms", type=int, default=None, help="Hik SDK frame timeout in milliseconds.")
    parser.add_argument("--camera-retry-interval", type=float, default=None, help="Seconds between camera reopen attempts. 0 disables retry.")
    parser.add_argument("--conf", type=float, default=None, help="Confidence threshold.")
    parser.add_argument("--fps", type=float, default=None, help="Detection FPS, default 2.")
    parser.add_argument("--frame-id", default=None, help="Frame ID for detection_status output.")
    parser.add_argument("--backend-url", default=None, help="Backend base URL.")
    parser.add_argument("--submit", action="store_true", default=None, help="Submit detection_status to backend.")
    parser.add_argument("--save-latest", default=None, help="Optional path to save latest detection image.")
    parser.add_argument("--max-det", type=int, default=None, help="Maximum detections kept after NMS.")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Print detection_status JSON and do not submit.")
    parser.add_argument("--output-layout", choices=OUTPUT_LAYOUTS, default=None, help="6-column RKNN output layout.")
    parser.add_argument("--submit-interval", type=float, default=None, help="Minimum seconds between backend submissions. Default follows FPS.")
    parser.add_argument("--read-fail-limit", type=int, default=None, help="Consecutive frame read failures before reporting camera offline.")
    parser.add_argument("--max-frames", type=int, default=None, help="Optional validation limit. 0 means run until Ctrl+C.")
    parser.add_argument("--save-debug-frames", action="store_true", default=None, help="Save per-frame input image, output image, and detection JSON.")
    parser.add_argument("--debug-frame-dir", default=None, help="Directory for debug frame files.")
    parser.add_argument("--debug-every-n", type=int, default=None, help="Save one debug frame set every N frames.")
    parser.add_argument("--hold-seconds", type=float, default=None, help="Seconds to keep selected detections for display stability.")
    parser.add_argument("--hold-classes", default=None, help="Comma-separated classes to hold, e.g. person,obstacle.")
    parser.add_argument("--event-min-confidence", type=float, default=None, help="Minimum confidence for visual events.")
    parser.add_argument("--event-min-area-ratio", type=float, default=None, help="Minimum bbox area ratio for obstacle events.")
    parser.add_argument("--blockage-frames-required", type=int, default=None, help="Consecutive obstacle frames required for possible_blockage.")
    parser.add_argument("--person-event-interval", type=float, default=None, help="Minimum seconds between person_detected events.")
    parser.add_argument("--obstacle-event-interval", type=float, default=None, help="Minimum seconds between obstacle_detected events.")
    parser.add_argument("--blockage-event-interval", type=float, default=None, help="Minimum seconds between possible_blockage events.")
    raw_args = parser.parse_args()

    try:
        args = _merge_config(raw_args)
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

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


def _merge_config(raw_args: argparse.Namespace) -> argparse.Namespace:
    values = dict(DEFAULT_OPTIONS)
    config_path = getattr(raw_args, "config", None)
    if config_path:
        config_file = Path(config_path)
        if not config_file.exists():
            raise RuntimeError(f"配置文件不存在：{config_file}")
        try:
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"配置文件不是合法 JSON：{exc}") from exc
        if not isinstance(config_data, dict):
            raise RuntimeError("配置文件顶层必须是 JSON object")
        unknown_fields = sorted(set(config_data) - CONFIG_FIELDS)
        if unknown_fields:
            raise RuntimeError(f"配置文件包含未知字段：{', '.join(unknown_fields)}")
        values.update(config_data)

    for key, value in vars(raw_args).items():
        if key == "config" or value is None:
            continue
        values[key] = value

    if not values.get("model"):
        raise RuntimeError("缺少 model，请通过 --model 或配置文件提供")
    if not values.get("labels"):
        raise RuntimeError("缺少 labels，请通过 --labels 或配置文件提供")
    if values["output_layout"] not in OUTPUT_LAYOUTS:
        raise RuntimeError(f"output_layout 必须是以下之一：{', '.join(OUTPUT_LAYOUTS)}")

    values["camera"] = str(values["camera"])
    values["camera_backend"] = str(values["camera_backend"]).lower()
    if values["camera_backend"] not in {"auto", "usb", "hik"}:
        raise RuntimeError("camera_backend 必须是 auto、usb 或 hik")
    values["hik_index"] = int(values["hik_index"])
    values["hik_serial"] = None if values["hik_serial"] in (None, "") else str(values["hik_serial"])
    values["hik_timeout_ms"] = int(values["hik_timeout_ms"])
    values["camera_retry_interval"] = max(0.0, float(values["camera_retry_interval"]))
    if values["hik_params"] is None:
        values["hik_params"] = {}
    if not isinstance(values["hik_params"], dict):
        raise RuntimeError("hik_params 必须是 JSON object")
    values["conf"] = float(values["conf"])
    values["fps"] = float(values["fps"])
    values["submit"] = bool(values["submit"])
    values["dry_run"] = bool(values["dry_run"])
    values["max_det"] = int(values["max_det"])
    values["submit_interval"] = float(values["submit_interval"])
    values["read_fail_limit"] = int(values["read_fail_limit"])
    values["max_frames"] = int(values["max_frames"])
    values["save_debug_frames"] = bool(values["save_debug_frames"])
    values["debug_frame_dir"] = str(values["debug_frame_dir"])
    values["debug_every_n"] = max(1, int(values["debug_every_n"]))
    values["hold_seconds"] = float(values["hold_seconds"])
    values["hold_classes"] = _normalize_hold_classes(values["hold_classes"])
    values["event_min_confidence"] = float(values["event_min_confidence"])
    values["event_min_area_ratio"] = float(values["event_min_area_ratio"])
    values["blockage_frames_required"] = int(values["blockage_frames_required"])
    values["person_event_interval"] = float(values["person_event_interval"])
    values["obstacle_event_interval"] = float(values["obstacle_event_interval"])
    values["blockage_event_interval"] = float(values["blockage_event_interval"])
    return argparse.Namespace(**values)


def _normalize_hold_classes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise RuntimeError("hold_classes 必须是逗号分隔字符串或字符串数组")


def run_service(args: argparse.Namespace) -> int:
    camera: CameraSource | None = None
    runner: RknnYoloRunner | None = None
    final_status: dict[str, Any] | None = None
    final_status_submitted = False

    try:
        camera = _open_camera_or_report(args)
        if camera is None:
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

        throttler = EventThrottler(_event_intervals_from_args(args))
        hold_cache = RecentDetectionHold(args.hold_seconds, set(args.hold_classes))
        frame_interval = 1.0 / max(args.fps, 0.1)
        submit_interval = args.submit_interval if args.submit_interval > 0 else frame_interval
        last_submit_at = 0.0
        frame_count = 0
        blockage_frames = 0
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
                    if args.camera_retry_interval > 0 and args.max_frames <= 0:
                        camera.release()
                        camera = _open_camera_or_report(args)
                        if camera is None:
                            final_status = status
                            final_status_submitted = args.submit and not args.dry_run
                            return 3
                        read_failures = 0
                        _sleep_until_next(loop_started, frame_interval)
                        continue
                    final_status = status
                    final_status_submitted = args.submit and not args.dry_run
                    return 3
                _sleep_until_next(loop_started, frame_interval)
                continue

            read_failures = 0
            frame_count += 1
            frame_seq = frame_count
            timestamp = _utc_now()
            width, height = _frame_dimensions(frame)
            current_objects: list[dict[str, Any]] = []
            stats = None
            try:
                current_objects, stats = runner.infer_frame_with_stats(frame, color_order=camera.color_order)
                if _has_current_event_obstacle(current_objects, args, width, height):
                    blockage_frames += 1
                else:
                    blockage_frames = 0
                display_objects = hold_cache.update(current_objects, timestamp=timestamp, now=time.monotonic())
                status = runner.build_status(
                    display_objects,
                    timestamp=timestamp,
                    blockage_frames=blockage_frames,
                    blockage_frames_required=args.blockage_frames_required,
                    event_min_confidence=args.event_min_confidence,
                    event_min_area_ratio=args.event_min_area_ratio,
                    image_width=width,
                    image_height=height,
                )
                status["events"] = throttler.filter(status.get("events", []), time.monotonic())
                _print_frame_stats(frame_seq, stats, current_objects)
            except Exception as exc:
                status = _service_status(args, False, "yolo_inference_error", "error", f"YOLO 推理失败：{exc}")
                print(status["events"][0]["message"], file=sys.stderr)

            if args.save_latest:
                try:
                    draw_detections_on_array(frame, Path(args.save_latest), status.get("objects", []), color_order=camera.color_order)
                except Exception as exc:
                    print(f"Save latest detection image failed: {exc}", file=sys.stderr)

            if args.save_debug_frames and frame_seq % args.debug_every_n == 0:
                try:
                    _save_debug_frame_set(args, frame_seq, frame, camera.color_order, current_objects, status, stats)
                except Exception as exc:
                    print(f"Save debug frame set failed: {exc}", file=sys.stderr)

            _emit_status(status, dry_run=args.dry_run)
            now = time.monotonic()
            if args.submit and not args.dry_run and now - last_submit_at >= submit_interval:
                _submit_status(args.backend_url, status)
                last_submit_at = now

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


def _event_intervals_from_args(args: argparse.Namespace) -> dict[str, float]:
    return {
        "person_detected": args.person_event_interval,
        "obstacle_detected": args.obstacle_event_interval,
        "possible_blockage": args.blockage_event_interval,
    }


def _frame_dimensions(frame: Any) -> tuple[int | None, int | None]:
    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        return None, None
    return int(shape[1]), int(shape[0])


def _has_current_event_obstacle(objects: list[dict[str, Any]], args: argparse.Namespace, width: int | None, height: int | None) -> bool:
    return any(
        item.get("class_name") in OBSTACLE_CLASSES
        and float(item.get("confidence", 0.0)) >= args.event_min_confidence
        and _bbox_area_ratio(item.get("bbox_xyxy", []), width, height) >= args.event_min_area_ratio
        for item in objects
    )


def _bbox_area_ratio(bbox: list[float], width: int | None, height: int | None) -> float:
    if not width or not height or len(bbox) < 4:
        return 1.0
    x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    frame_area = float(width * height)
    return area / frame_area if frame_area > 0 else 0.0


def _print_frame_stats(frame_seq: int, stats: Any, objects: list[dict[str, Any]]) -> None:
    top = ", ".join(f"{item['class_name']}:{float(item['confidence']):.2f}" for item in objects[:3]) or "none"
    if stats is None:
        print(f"frame={frame_seq} raw=unknown conf=unknown nms=unknown final={len(objects)} top={top}", file=sys.stderr)
        return
    print(
        f"frame={frame_seq} raw={stats.raw_candidate_count} "
        f"conf={stats.confidence_passed_count} nms={stats.nms_passed_count} "
        f"final={stats.final_detection_count} top={top}",
        file=sys.stderr,
    )


def _save_debug_frame_set(
    args: argparse.Namespace,
    frame_seq: int,
    frame: Any,
    color_order: str,
    current_objects: list[dict[str, Any]],
    status: dict[str, Any],
    stats: Any,
) -> None:
    debug_dir = Path(args.debug_frame_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    prefix = debug_dir / f"frame_{frame_seq:06d}"
    _save_frame_array(frame, prefix.with_name(prefix.name + "_input.jpg"), color_order=color_order)
    draw_detections_on_array(frame, prefix.with_name(prefix.name + "_output.jpg"), current_objects, color_order=color_order)
    payload = {
        "frame_seq": frame_seq,
        "stats": _stats_to_dict(stats),
        "current_objects": current_objects,
        "detection_status": status,
    }
    prefix.with_name(prefix.name + "_detection.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_frame_array(frame: Any, output_path: Path, *, color_order: str) -> None:
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"保存 debug 输入帧需要 numpy 和 Pillow：{exc}") from exc
    array = np.asarray(frame)
    if array.ndim != 3 or array.shape[2] < 3:
        raise RuntimeError(f"图像帧格式不支持：shape={array.shape}")
    if color_order.lower() == "bgr":
        rgb_array = array[:, :, :3][:, :, ::-1]
    elif color_order.lower() == "rgb":
        rgb_array = array[:, :, :3]
    else:
        raise RuntimeError(f"不支持的颜色顺序：{color_order}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(rgb_array).astype("uint8"), mode="RGB").save(output_path)


def _stats_to_dict(stats: Any) -> dict[str, int]:
    if stats is None:
        return {}
    return {
        "raw_candidate_count": int(stats.raw_candidate_count),
        "confidence_passed_count": int(stats.confidence_passed_count),
        "nms_passed_count": int(stats.nms_passed_count),
        "final_detection_count": int(stats.final_detection_count),
    }


def _open_camera_or_report(args: argparse.Namespace) -> CameraSource | None:
    while True:
        camera = _open_camera(args)
        if camera is not None:
            return camera
        status = _service_status(args, False, "camera_unavailable", "warning", "摄像头不可用或无法打开")
        _emit_status(status, dry_run=args.dry_run)
        _maybe_submit(args, status, force=True)
        if args.camera_retry_interval <= 0 or args.max_frames > 0:
            return None
        print(f"Camera unavailable; retrying in {args.camera_retry_interval:.1f}s.", file=sys.stderr)
        time.sleep(args.camera_retry_interval)


def _open_camera(args: argparse.Namespace) -> CameraSource | None:
    if args.camera_backend == "hik":
        return _open_hik_camera(args)

    camera = _open_usb_camera(args.camera)
    if camera is not None:
        return camera

    if args.camera_backend == "auto":
        hik_camera = _open_hik_camera(args)
        if hik_camera is not None:
            return hik_camera
    return None


def _open_usb_camera(camera_arg: str) -> CameraSource | None:
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


def _open_hik_camera(args: argparse.Namespace) -> CameraSource | None:
    try:
        from hik_camera_source import HikCameraSource
    except Exception as exc:
        print(f"Hik camera backend unavailable: {exc}", file=sys.stderr)
        return None
    camera = HikCameraSource(index=args.hik_index, serial=args.hik_serial, timeout_ms=args.hik_timeout_ms, params=args.hik_params)
    if camera.is_opened():
        label = getattr(camera, "device_label", "")
        print(f"Hik camera opened via MVS SDK: {label}", file=sys.stderr)
        return camera
    error = getattr(camera, "last_error", "unknown error")
    camera.release()
    print(f"Hik camera could not open: {error}", file=sys.stderr)
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
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2.0) as response:
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
