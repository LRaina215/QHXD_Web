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
OUTPUT_LAYOUTS = ("auto", "xyxy_score_class", "xyxy_class_score", "class_score_xyxy")


@dataclass(frozen=True)
class ImageMeta:
    original_width: int
    original_height: int
    input_width: int = INPUT_SIZE
    input_height: int = INPUT_SIZE


@dataclass
class DetectionPipelineStats:
    raw_candidate_count: int = 0
    confidence_passed_count: int = 0
    nms_passed_count: int = 0
    final_detection_count: int = 0

    def add(self, other: "DetectionPipelineStats") -> None:
        self.raw_candidate_count += other.raw_candidate_count
        self.confidence_passed_count += other.confidence_passed_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one RKNN YOLO image inference on RK3588.")
    parser.add_argument("--model", required=True, help="Path to a .rknn model file.")
    parser.add_argument("--image", required=True, help="Path to an input image.")
    parser.add_argument("--labels", required=True, help="Path to a labels.txt file.")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold.")
    parser.add_argument("--frame-id", default="camera_front", help="Frame ID for detection_status output.")
    parser.add_argument("--draw-output", default=None, help="Optional path to save an image with detection boxes drawn.")
    parser.add_argument("--debug-raw", action="store_true", help="Print raw RKNN output rows and per-column stats to stderr.")
    parser.add_argument("--output-layout", choices=OUTPUT_LAYOUTS, default="auto", help="6-column RKNN output layout.")
    parser.add_argument("--max-det", type=int, default=50, help="Maximum detections kept after NMS.")
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
    if args.debug_raw:
        _print_input_tensor_debug(input_tensor, np)
    try:
        with _capture_native_stdout_to_stderr():
            outputs = _run_rknn_inference(RKNNLite, model_path, input_tensor)
    except Exception as exc:
        return _fail(f"RKNN 推理失败：{exc}")

    _print_output_debug(outputs, np)
    if args.debug_raw:
        _print_raw_output_debug(outputs, np)
    objects = _parse_outputs(
        outputs,
        labels,
        args.conf,
        DEFAULT_IOU_THRESHOLD,
        image_meta,
        args.output_layout,
        max(0, args.max_det),
        np,
    )
    if args.draw_output:
        try:
            _draw_detections(image_path, Path(args.draw_output), objects)
        except RuntimeError as exc:
            return _fail(str(exc))
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


class RknnYoloRunner:
    def __init__(
        self,
        model_path: str | Path,
        labels_path: str | Path,
        *,
        conf: float = 0.25,
        output_layout: str = "xyxy_score_class",
        max_det: int = 20,
        frame_id: str = "camera_front",
        source: str = "rk3588-rknn-yolo26",
    ) -> None:
        self.model_path = Path(model_path)
        self.labels_path = Path(labels_path)
        self.conf = conf
        self.output_layout = output_layout
        self.max_det = max_det
        self.frame_id = frame_id
        self.source = source
        self.labels: list[str] = []
        self.np = None
        self.rknn_cls = None
        self.rknn = None

    @property
    def model_name(self) -> str:
        return self.model_path.name

    def load(self) -> "RknnYoloRunner":
        if not self.model_path.exists():
            raise RuntimeError(f"模型文件不存在：{self.model_path}")
        if not self.labels_path.exists():
            raise RuntimeError(f"标签文件不存在：{self.labels_path}")

        try:
            import numpy as np
            from rknnlite.api import RKNNLite
        except ImportError as exc:
            raise RuntimeError(
                "缺少 RKNN Runtime / RKNN-Toolkit-Lite2 或 numpy。"
                "请在 RK3588 设备端安装 rknn-toolkit-lite2 和 numpy 后再运行。"
                f" 原始错误：{exc}"
            ) from exc

        labels = _load_labels(self.labels_path)
        if not labels:
            raise RuntimeError(f"标签文件为空：{self.labels_path}")

        rknn = RKNNLite()
        try:
            with _capture_native_stdout_to_stderr():
                ret = rknn.load_rknn(str(self.model_path))
                if ret != 0:
                    raise RuntimeError(f"RKNN 模型加载失败，返回码：{ret}")
                ret = rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_AUTO)
                if ret != 0:
                    raise RuntimeError(f"RKNN Runtime 初始化失败，返回码：{ret}")
        except Exception:
            try:
                rknn.release()
            except Exception:
                pass
            raise

        self.np = np
        self.rknn_cls = RKNNLite
        self.rknn = rknn
        self.labels = labels
        return self

    def infer_frame(self, frame: Any, *, color_order: str = "bgr") -> list[dict[str, Any]]:
        objects, _stats = self.infer_frame_with_stats(frame, color_order=color_order)
        return objects

    def infer_frame_with_stats(self, frame: Any, *, color_order: str = "bgr") -> tuple[list[dict[str, Any]], DetectionPipelineStats]:
        if self.rknn is None or self.np is None:
            raise RuntimeError("RKNN YOLO runner 尚未 load()")
        input_tensor, image_meta = _preprocess_frame_array(frame, self.np, color_order=color_order)
        with _capture_native_stdout_to_stderr():
            outputs = self.rknn.inference(inputs=[input_tensor])
        return _parse_outputs_with_stats(
            outputs,
            self.labels,
            self.conf,
            DEFAULT_IOU_THRESHOLD,
            image_meta,
            self.output_layout,
            max(0, self.max_det),
            self.np,
        )

    def build_status(
        self,
        objects: list[dict[str, Any]],
        *,
        enabled: bool = True,
        timestamp: str | None = None,
        blockage_frames: int = 0,
        blockage_frames_required: int = 3,
        event_min_confidence: float = 0.0,
        event_min_area_ratio: float = 0.0,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> dict[str, Any]:
        return build_detection_status(
            objects,
            model_name=self.model_name,
            frame_id=self.frame_id,
            source=self.source,
            enabled=enabled,
            timestamp=timestamp,
            blockage_frames=blockage_frames,
            blockage_frames_required=blockage_frames_required,
            event_min_confidence=event_min_confidence,
            event_min_area_ratio=event_min_area_ratio,
            image_width=image_width,
            image_height=image_height,
        )

    def release(self) -> None:
        if self.rknn is not None:
            try:
                self.rknn.release()
            finally:
                self.rknn = None


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
    return _preprocess_frame_array(image, np, color_order="bgr")


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

    return _preprocess_frame_array(np.asarray(image), np, color_order="rgb")


def _preprocess_frame_array(frame: Any, np, *, color_order: str = "bgr") -> tuple[Any, ImageMeta]:
    array = np.asarray(frame)
    if array.ndim != 3 or array.shape[2] < 3:
        raise RuntimeError(f"图像帧格式不支持：shape={array.shape}")

    height, width = array.shape[:2]
    color_order = color_order.lower()
    if color_order == "bgr":
        rgb_image = array[:, :, :3][:, :, ::-1]
    elif color_order == "rgb":
        rgb_image = array[:, :, :3]
    else:
        raise RuntimeError(f"不支持的颜色顺序：{color_order}")

    rgb_image = np.ascontiguousarray(rgb_image)
    resized = _resize_rgb_image(rgb_image, np)
    input_tensor = np.expand_dims(resized.astype(np.float32) / 255.0, axis=0)
    return input_tensor, ImageMeta(original_width=width, original_height=height)


def _resize_rgb_image(rgb_image: Any, np):
    try:
        import cv2
    except ImportError:
        from PIL import Image

        image = Image.fromarray(np.asarray(rgb_image).astype("uint8"), mode="RGB")
        return np.asarray(image.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR))

    return cv2.resize(rgb_image, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)


def _draw_detections(image_path: Path, output_path: Path, objects: list[dict[str, Any]]) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("保存画框图片需要 Pillow。") from exc

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"无法读取待画框图片：{image_path}，原始错误：{exc}") from exc

    _save_detection_visualization(image, output_path, objects)


def draw_detections_on_array(image_array: Any, output_path: Path, objects: list[dict[str, Any]], *, color_order: str = "bgr") -> None:
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("保存画框图片需要 numpy 和 Pillow。") from exc

    array = np.asarray(image_array)
    if array.ndim != 3 or array.shape[2] < 3:
        raise RuntimeError(f"图像帧格式不支持：shape={array.shape}")

    if color_order.lower() == "bgr":
        rgb_array = array[:, :, :3][:, :, ::-1]
    elif color_order.lower() == "rgb":
        rgb_array = array[:, :, :3]
    else:
        raise RuntimeError(f"不支持的颜色顺序：{color_order}")

    image = Image.fromarray(np.ascontiguousarray(rgb_array).astype("uint8"), mode="RGB")
    _save_detection_visualization(image, output_path, objects)


def _save_detection_visualization(image, output_path: Path, objects: list[dict[str, Any]]) -> None:
    try:
        from PIL import ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("保存画框图片需要 Pillow。") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    for item in objects:
        x1, y1, x2, y2 = [float(value) for value in item["bbox_xyxy"]]
        label = f'{item["class_name"]} {float(item["confidence"]):.2f}'
        color = _color_for_label(item["class_name"])
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        text_box = draw.textbbox((x1, y1), label, font=font)
        text_w = text_box[2] - text_box[0]
        text_h = text_box[3] - text_box[1]
        label_y = max(0, y1 - text_h - 4)
        draw.rectangle([x1, label_y, x1 + text_w + 6, label_y + text_h + 4], fill=color)
        draw.text((x1 + 3, label_y + 2), label, fill=(255, 255, 255), font=font)

    image.save(output_path)
    print(f"Saved detection visualization: {output_path}", file=sys.stderr)


def _color_for_label(label: str) -> tuple[int, int, int]:
    palette = [
        (239, 68, 68),
        (34, 197, 94),
        (59, 130, 246),
        (245, 158, 11),
        (168, 85, 247),
        (20, 184, 166),
    ]
    return palette[sum(ord(char) for char in label) % len(palette)]


def _print_input_tensor_debug(input_tensor: Any, np) -> None:
    array = np.asarray(input_tensor)
    if array.size == 0:
        print(f"input_tensor shape={array.shape}", file=sys.stderr)
        print(f"input_tensor dtype={array.dtype}", file=sys.stderr)
        print("input_tensor min=nan", file=sys.stderr)
        print("input_tensor max=nan", file=sys.stderr)
        return
    finite = array[np.isfinite(array)]
    min_value = float(finite.min()) if finite.size else float("nan")
    max_value = float(finite.max()) if finite.size else float("nan")
    print(f"input_tensor shape={array.shape}", file=sys.stderr)
    print(f"input_tensor dtype={array.dtype}", file=sys.stderr)
    print(f"input_tensor min={min_value:.6f}", file=sys.stderr)
    print(f"input_tensor max={max_value:.6f}", file=sys.stderr)


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


def _parse_outputs(
    outputs: Any,
    labels: list[str],
    conf_threshold: float,
    iou_threshold: float,
    image_meta: ImageMeta,
    output_layout: str,
    max_det: int,
    np,
) -> list[dict[str, Any]]:
    objects, _stats = _parse_outputs_with_stats(
        outputs, labels, conf_threshold, iou_threshold, image_meta, output_layout, max_det, np
    )
    return objects


def _parse_outputs_with_stats(
    outputs: Any,
    labels: list[str],
    conf_threshold: float,
    iou_threshold: float,
    image_meta: ImageMeta,
    output_layout: str,
    max_det: int,
    np,
) -> tuple[list[dict[str, Any]], DetectionPipelineStats]:
    candidates: list[dict[str, Any]] = []
    stats = DetectionPipelineStats()
    if not outputs or max_det == 0:
        return [], stats

    for output in outputs:
        for matrix in _output_to_prediction_matrices(output, labels, np):
            decoded, matrix_stats = _decode_prediction_matrix_with_stats(
                matrix, labels, conf_threshold, image_meta, output_layout, np
            )
            candidates.extend(decoded)
            stats.add(matrix_stats)

    nms_objects = _nms(candidates, iou_threshold)
    stats.nms_passed_count = len(nms_objects)
    final_objects = nms_objects[:max_det]
    stats.final_detection_count = len(final_objects)
    return final_objects, stats


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


def _decode_prediction_matrix(
    matrix,
    labels: list[str],
    conf_threshold: float,
    image_meta: ImageMeta,
    output_layout: str,
    np,
) -> list[dict[str, Any]]:
    detections, _stats = _decode_prediction_matrix_with_stats(
        matrix, labels, conf_threshold, image_meta, output_layout, np
    )
    return detections


def _decode_prediction_matrix_with_stats(
    matrix,
    labels: list[str],
    conf_threshold: float,
    image_meta: ImageMeta,
    output_layout: str,
    np,
) -> tuple[list[dict[str, Any]], DetectionPipelineStats]:
    stats = DetectionPipelineStats()
    if matrix.ndim != 2 or matrix.shape[1] < 6:
        return [], stats

    detections: list[dict[str, Any]] = []
    class_count = len(labels)
    feature_count = matrix.shape[1]
    six_column_layout = None
    if feature_count == 6:
        six_column_layout = _resolve_six_column_layout(matrix, labels, output_layout, np)

    for raw_row in matrix:
        row = np.asarray(raw_row, dtype=np.float32)
        if not np.isfinite(row).all():
            continue
        stats.raw_candidate_count += 1

        if feature_count == 6:
            decoded = _decode_six_column_row(row, six_column_layout)
            if decoded is None:
                continue
            bbox_values, confidence, class_id = decoded
            assume_xywh = False
        elif feature_count >= class_count + 5:
            bbox_values = row[:4]
            objectness = float(row[4])
            class_scores = row[5:5 + class_count]
            if class_scores.size == 0:
                continue
            class_id = int(class_scores.argmax())
            confidence = objectness * float(class_scores[class_id])
            assume_xywh = True
        elif feature_count >= class_count + 4:
            bbox_values = row[:4]
            class_scores = row[4:4 + class_count]
            if class_scores.size == 0:
                continue
            class_id = int(class_scores.argmax())
            confidence = float(class_scores[class_id])
            assume_xywh = True
        else:
            continue

        if confidence < conf_threshold:
            continue
        stats.confidence_passed_count += 1
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

    return detections, stats


def _print_raw_output_debug(outputs: Any, np) -> None:
    print("===== RKNN raw output debug =====", file=sys.stderr)
    if outputs is None:
        print("No outputs", file=sys.stderr)
        print("=================================", file=sys.stderr)
        return

    for index, output in enumerate(outputs):
        array = np.asarray(output)
        print(f"Output {index}: shape={array.shape}, dtype={array.dtype}", file=sys.stderr)
        matrix = _raw_debug_matrix(array, np)
        if matrix is None or matrix.size == 0:
            print("  empty or unsupported raw layout", file=sys.stderr)
            continue
        print("  first 20 raw rows:", file=sys.stderr)
        for row_index, row in enumerate(matrix[:20]):
            print(f"  row {row_index}: {_format_debug_row(row)}", file=sys.stderr)
        print("  per-column stats:", file=sys.stderr)
        for column_index in range(matrix.shape[1]):
            column = matrix[:, column_index]
            finite = column[np.isfinite(column)]
            if finite.size == 0:
                print(f"  col {column_index}: min=nan max=nan mean=nan finite=0/{len(column)}", file=sys.stderr)
                continue
            print(
                f"  col {column_index}: "
                f"min={float(finite.min()):.6f} "
                f"max={float(finite.max()):.6f} "
                f"mean={float(finite.mean()):.6f} "
                f"finite={finite.size}/{len(column)}",
                file=sys.stderr,
            )
    print("=================================", file=sys.stderr)


def _raw_debug_matrix(array, np):
    if array.ndim == 3 and array.shape[0] == 1:
        array = array[0]
    elif array.ndim > 2:
        squeezed = array.squeeze()
        if squeezed.ndim == 2:
            array = squeezed
        elif array.shape[-1] <= 256:
            array = array.reshape(-1, array.shape[-1])
        else:
            return None
    if array.ndim != 2:
        return None
    return np.asarray(array, dtype=np.float32)


def _format_debug_row(row) -> str:
    return "[" + ", ".join(f"{float(value):.6g}" for value in row) + "]"


def _resolve_six_column_layout(matrix, labels: list[str], requested_layout: str, np) -> str:
    if requested_layout != "auto":
        return requested_layout

    scores = {
        layout: _score_six_column_layout(matrix, layout, len(labels), np)
        for layout in OUTPUT_LAYOUTS
        if layout != "auto"
    }
    best_layout = max(scores, key=scores.get)
    print(f"Inferred 6-column output layout: {best_layout} (scores={scores})", file=sys.stderr)
    return best_layout


def _score_six_column_layout(matrix, layout: str, class_count: int, np) -> float:
    rows = np.asarray(matrix, dtype=np.float32)
    rows = rows[np.isfinite(rows).all(axis=1)]
    if rows.size == 0:
        return -1.0

    if layout == "xyxy_score_class":
        coords = rows[:, :4]
        score_values = rows[:, 4]
        class_values = rows[:, 5]
    elif layout == "xyxy_class_score":
        coords = rows[:, :4]
        class_values = rows[:, 4]
        score_values = rows[:, 5]
    elif layout == "class_score_xyxy":
        class_values = rows[:, 0]
        score_values = rows[:, 1]
        coords = rows[:, 2:6]
    else:
        return -1.0

    score_ratio = _ratio((score_values >= 0.0) & (score_values <= 1.0))
    class_ratio = _ratio((class_values >= 0.0) & (class_values < class_count) & (np.abs(class_values - np.round(class_values)) < 0.01))
    coord_ratio = _coordinate_valid_ratio(coords, np)
    return score_ratio * 0.4 + class_ratio * 0.4 + coord_ratio * 0.2


def _coordinate_valid_ratio(coords, np) -> float:
    if coords.shape[1] != 4:
        return 0.0
    x1 = coords[:, 0]
    y1 = coords[:, 1]
    x2 = coords[:, 2]
    y2 = coords[:, 3]
    plausible_range = (np.abs(coords) <= INPUT_SIZE * 4).all(axis=1)
    valid_xyxy = (x2 > x1) & (y2 > y1) & plausible_range
    normalized = (coords >= -0.01).all(axis=1) & (coords <= 1.5).all(axis=1)
    return _ratio(valid_xyxy | normalized)


def _ratio(mask) -> float:
    return float(mask.mean()) if len(mask) else 0.0


def _decode_six_column_row(row, layout: str):
    if layout == "xyxy_score_class":
        return row[:4], float(row[4]), int(round(float(row[5])))
    if layout == "xyxy_class_score":
        return row[:4], float(row[5]), int(round(float(row[4])))
    if layout == "class_score_xyxy":
        return row[2:6], float(row[1]), int(round(float(row[0])))
    return None


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
