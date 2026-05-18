#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from detection_status_builder import build_detection_status


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

    model_path = Path(args.model)
    image_path = Path(args.image)
    labels_path = Path(args.labels)

    if not model_path.exists():
        return _fail(
            f"模型文件不存在：{model_path}。请将 .rknn 模型放入 experiments/rknn_yolo/models/ 后重试。"
        )
    if not image_path.exists():
        return _fail(f"图片文件不存在：{image_path}。请将测试图片放入 experiments/rknn_yolo/samples/。")
    if not labels_path.exists():
        return _fail(f"标签文件不存在：{labels_path}。请提供与模型匹配的 labels.txt。")

    try:
        import cv2
        import numpy as np
        from rknnlite.api import RKNNLite
    except ImportError as exc:
        return _fail(
            "缺少 RKNN Runtime / RKNN-Toolkit-Lite2 或图像依赖。"
            "请在 RK3588 设备端安装 rknn-toolkit-lite2、opencv-python 和 numpy 后再运行。"
            f" 原始错误：{exc}"
        )

    labels = [line.strip() for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    image = cv2.imread(str(image_path))
    if image is None:
        return _fail(f"无法读取图片：{image_path}")

    rknn = RKNNLite()
    try:
        ret = rknn.load_rknn(str(model_path))
        if ret != 0:
            return _fail(f"RKNN 模型加载失败，返回码：{ret}")
        ret = rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_AUTO)
        if ret != 0:
            return _fail(f"RKNN Runtime 初始化失败，返回码：{ret}")

        input_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        outputs = rknn.inference(inputs=[input_image])
    except Exception as exc:
        return _fail(f"RKNN 推理失败：{exc}")
    finally:
        try:
            rknn.release()
        except Exception:
            pass

    objects = _parse_outputs(outputs, labels, args.conf, np)
    timestamp = datetime.now(timezone.utc).isoformat()
    if args.format == "detection_status":
        payload = {
            "detection_status": build_detection_status(
                objects,
                model_name=model_path.name,
                frame_id=args.frame_id,
                timestamp=timestamp,
            )
        }
    else:
        payload = {"timestamp": timestamp, "objects": objects}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _parse_outputs(outputs: Any, labels: list[str], conf_threshold: float, np) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if not outputs:
        return objects

    for output in outputs:
        array = np.asarray(output).squeeze()
        if array.ndim != 2:
            continue
        if array.shape[0] in {6, 7} and array.shape[1] != 6:
            array = array.T
        if array.shape[1] < 6:
            continue

        for row in array:
            confidence = float(row[4])
            if confidence < conf_threshold:
                continue
            class_id = int(row[5])
            class_name = labels[class_id] if 0 <= class_id < len(labels) else str(class_id)
            objects.append(
                {
                    "class_name": class_name,
                    "confidence": round(confidence, 4),
                    "bbox_xyxy": [round(float(value), 2) for value in row[:4]],
                }
            )
    return objects


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
