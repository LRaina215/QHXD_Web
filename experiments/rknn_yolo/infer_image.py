#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from detection_status_builder import build_detection_status

INPUT_SIZE = 640
DEFAULT_IOU_THRESHOLD = 0.45


@dataclass(frozen=True)
class ImageMeta:
    original_width: int
    original_height: int
    input_width: int = INPUT_SIZE
    input_height: int = INPUT_SIZE


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one RKNN YOLO image inference on RK3588.")
    parser.add_argument("--model", required=True, help="Path to a .rknn model file.")
    parser.add_argument("--image", required=True, help="Path to an input image.")
    parser.add_argument("--labels", required=True, help="Path to a labels.txt file.")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold.")
    parser.add_argument("--frame-id", default="camera_front", help="Frame ID for detection_status output.")
    parser.add_argument(
        "--format",
        choices=["detections", "detection_status"],
        default="detections",
        help="Output plain detections or the Phase 4A detection_status wrapper.",
    )
    args = parser.parse_args()
    json_stdout_fd = _redirect_stdout_to_stderr()

    model_path = Path(args.model)
    image_path = Path(args.image)
    labels_path = Path(args.labels)

    if not model_path.exists():
        return _fail(f"模型文件不存在：{model_path}。请将 .rknn 模型放入 experiments/rknn_yolo/models/ 后重试。")
    if not image_path.exists():
        return _fail(f"图片文件不存在：{image_path}。请将测试图片放入 experiments/rknn_yolo/samples/。")
    if not labels_path.exists():
        return _fail(f"标签文件不存在：{labels_path}。请提供与模型类别顺序一致的 labels.txt。")

    try:
        import numpy as np
        from rknnlite.api import RKNNLite
    except ImportError as exc:
        return _fail(
            "缺少 RKNN Runtime / RKNN-Toolkit-Lite2 或 numpy。"
            "请在 RK3588 设备端安装 rknn-toolkit-lite2 和 numpy 后再运行。"
            f" 原始错误：{exc}"
        )

    labels = _load_labels(labels_path)
    if not labels:
        return _fail(f"标签文件为空：{labels_path}")

    try:
        input_tensor, image_meta = _load_and_preprocess_image(image_path, np)
    except RuntimeError as exc:
        return _fail(str(exc))
    try:
        with _capture_native_stdout_to_stderr():
            outputs = _run_rknn_inference(RKNNLite, model_path, input_tensor)
    except Exception as exc:
        return _fail(f"RKNN 推理失败：{exc}")

    _print_output_debug(outputs, np)
    objects = _parse_outputs(outputs, labels, args.conf, DEFAULT_IOU_THRESHOLD, image_meta, np)
    timestamp = datetime.now(timezone.utc).isoformat()
    if args.format == "detection_status":
        payload = {
            "detection_status": build_detection_status(
                objects,
                model_name=model_path.name,
                frame_id=args.frame_id,
                source="rk3588-rknn-yolo26",
                timestamp=timestamp,
            )
        }
    else:
        payload = {"timestamp": timestamp, "objects": objects}

    _write_json(payload, json_stdout_fd)
    return 0


def _load_labels(labels_path: Path) -> list[str]:
    return [line.strip() for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _redirect_stdout_to_stderr() -> int:
    sys.stdout.flush()
    json_stdout_fd = os.dup(1)
    os.dup2(2, 1)
    return json_stdout_fd


def _write_json(payload: dict[str, Any], json_stdout_fd: int) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    os.write(json_stdout_fd, data)
    os.close(json_stdout_fd)


def _run_rknn_inference(rknn_cls, model_path: Path, input_tensor):
    rknn = rknn_cls()
    try:
        ret = rknn.load_rknn(str(model_path))
        if ret != 0:
            raise RuntimeError(f"RKNN 模型加载失败，返回码：{ret}")
        ret = rknn.init_runtime(core_mask=rknn_cls.NPU_CORE_AUTO)
        if ret != 0:
            raise RuntimeError(f"RKNN Runtime 初始化失败，返回码：{ret}")
        return rknn.inference(inputs=[input_tensor])
    finally:
        try:
            rknn.release()
        except Exception:
            pass


@contextmanager
def _capture_native_stdout_to_stderr():
    sys.stdout.flush()
    original_stdout_fd = os.dup(1)
    with tempfile.TemporaryFile(mode="w+b") as captured_stdout:
        os.dup2(captured_stdout.fileno(), 1)
        try:
            yield
        finally:
            sys.stdout.flush()
            os.dup2(original_stdout_fd, 1)
            os.close(original_stdout_fd)
            captured_stdout.seek(0)
            captured = captured_stdout.read().decode("utf-8", errors="replace")
            if captured:
                print(captured, file=sys.stderr, end="" if captured.endswith("\n") else "\n")


def _load_and_preprocess_image(image_path: Path, np) -> tuple[Any, ImageMeta]:
    try:
        import cv2
    except ImportError:
        return _load_and_preprocess_with_pillow(image_path, np)

    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"无法读取图片：{image_path}")
    height, width = image.shape[:2]
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb_image, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
    input_tensor = np.expand_dims(resized, axis=0).astype(np.uint8)
    return input_tensor, ImageMeta(original_width=width, original_height=height)


def _load_and_preprocess_with_pillow(image_path: Path, np) -> tuple[Any, ImageMeta]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "缺少图片读取依赖：未安装 opencv-python，也未安装 Pillow。"
            "请安装其中任意一个后重试。"
        ) from exc

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"无法读取图片：{image_path}，原始错误：{exc}") from exc

    width, height = image.size
    resized = image.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    input_tensor = np.expand_dims(np.asarray(resized), axis=0).astype(np.uint8)
    return input_tensor, ImageMeta(original_width=width, original_height=height)


def _print_output_debug(outputs: Any, np) -> None:
    print("===== RKNN output debug =====", file=sys.stderr)
    if outputs is None:
        print("Number of outputs: 0 (None)", file=sys.stderr)
        print("=============================", file=sys.stderr)
        return

    print(f"Number of outputs: {len(outputs)}", file=sys.stderr)
    for index, output in enumerate(outputs):
        array = np.asarray(output)
        if array.size == 0:
            print(f"Output {index}: shape={array.shape}, dtype={array.dtype}, empty", file=sys.stderr)
            continue
        print(
            "Output "
            f"{index}: shape={array.shape}, dtype={array.dtype}, "
            f"min={float(array.min()):.6f}, max={float(array.max()):.6f}, mean={float(array.mean()):.6f}",
            file=sys.stderr,
        )
    print("=============================", file=sys.stderr)


def _parse_outputs(outputs: Any, labels: list[str], conf_threshold: float, iou_threshold: float, image_meta: ImageMeta, np) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not outputs:
        return []

    for output in outputs:
        for matrix in _output_to_prediction_matrices(output, labels, np):
            candidates.extend(_decode_prediction_matrix(matrix, labels, conf_threshold, image_meta, np))

    return _nms(candidates, iou_threshold)


def _output_to_prediction_matrices(output: Any, labels: list[str], np) -> list[Any]:
    array = np.asarray(output)
    if array.size == 0:
        return []

    if array.ndim == 3 and array.shape[0] == 1:
        array = array[0]

    if array.ndim == 2:
        return [_orient_prediction_matrix(array, labels)]

    if array.ndim == 4 and array.shape[0] == 1:
        array = array[0]
        if _looks_like_channel_first(array.shape, labels):
            return [array.reshape(array.shape[0], -1).T]
        if array.shape[-1] >= 6:
            return [array.reshape(-1, array.shape[-1])]

    squeezed = array.squeeze()
    if squeezed.ndim == 2:
        return [_orient_prediction_matrix(squeezed, labels)]
    return []


def _orient_prediction_matrix(matrix, labels: list[str]):
    rows, cols = matrix.shape
    max_feature_count = max(6, len(labels) + 5)
    if rows <= max_feature_count and cols > rows:
        return matrix.T
    return matrix


def _looks_like_channel_first(shape: tuple[int, ...], labels: list[str]) -> bool:
    if len(shape) != 3:
        return False
    channel_count = shape[0]
    return 6 <= channel_count <= max(6, len(labels) + 5)


def _decode_prediction_matrix(matrix, labels: list[str], conf_threshold: float, image_meta: ImageMeta, np) -> list[dict[str, Any]]:
    if matrix.ndim != 2 or matrix.shape[1] < 6:
        return []

    detections: list[dict[str, Any]] = []
    class_count = len(labels)
    feature_count = matrix.shape[1]

    for raw_row in matrix:
        row = np.asarray(raw_row, dtype=np.float32)
        if not np.isfinite(row).all():
            continue
        bbox_values: Any
        confidence: float
        class_id: int
        assume_xywh = True

        if feature_count == 6:
            bbox_values = row[:4]
            confidence = float(row[4])
            class_id = int(round(float(row[5])))
            assume_xywh = not _looks_like_xyxy(bbox_values)
        elif feature_count >= class_count + 5:
            bbox_values = row[:4]
            objectness = float(row[4])
            class_scores = row[5:5 + class_count]
            if class_scores.size == 0:
                continue
            class_id = int(class_scores.argmax())
            confidence = objectness * float(class_scores[class_id])
        elif feature_count >= class_count + 4:
            bbox_values = row[:4]
            class_scores = row[4:4 + class_count]
            if class_scores.size == 0:
                continue
            class_id = int(class_scores.argmax())
            confidence = float(class_scores[class_id])
        else:
            continue

        if confidence < conf_threshold:
            continue
        if not 0 <= class_id < class_count:
            continue

        bbox_xyxy = _convert_bbox(bbox_values, image_meta, assume_xywh=assume_xywh)
        if bbox_xyxy is None:
            continue

        detections.append(
            {
                "class_name": labels[class_id],
                "confidence": round(confidence, 4),
                "bbox_xyxy": [round(float(value), 2) for value in bbox_xyxy],
            }
        )

    return detections


def _looks_like_xyxy(values) -> bool:
    x1, y1, x2, y2 = [float(value) for value in values[:4]]
    return x2 > x1 and y2 > y1


def _convert_bbox(values, image_meta: ImageMeta, *, assume_xywh: bool) -> list[float] | None:
    x0, y0, x1_or_w, y1_or_h = [float(value) for value in values[:4]]
    if max(abs(x0), abs(y0), abs(x1_or_w), abs(y1_or_h)) <= 1.5:
        x0 *= image_meta.input_width
        x1_or_w *= image_meta.input_width
        y0 *= image_meta.input_height
        y1_or_h *= image_meta.input_height

    if assume_xywh:
        x1 = x0 - x1_or_w / 2.0
        y1 = y0 - y1_or_h / 2.0
        x2 = x0 + x1_or_w / 2.0
        y2 = y0 + y1_or_h / 2.0
    else:
        x1, y1, x2, y2 = x0, y0, x1_or_w, y1_or_h

    scale_x = image_meta.original_width / image_meta.input_width
    scale_y = image_meta.original_height / image_meta.input_height
    x1 *= scale_x
    x2 *= scale_x
    y1 *= scale_y
    y2 *= scale_y

    x1 = max(0.0, min(float(image_meta.original_width), x1))
    x2 = max(0.0, min(float(image_meta.original_width), x2))
    y1 = max(0.0, min(float(image_meta.original_height), y1))
    y2 = max(0.0, min(float(image_meta.original_height), y2))

    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _nms(detections: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    ordered = sorted(detections, key=lambda item: item["confidence"], reverse=True)
    selected: list[dict[str, Any]] = []

    while ordered:
        current = ordered.pop(0)
        selected.append(current)
        ordered = [
            item for item in ordered
            if _iou(item["bbox_xyxy"], current["bbox_xyxy"]) < iou_threshold
        ]

    return selected


def _iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
