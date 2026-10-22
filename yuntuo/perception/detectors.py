"""检测器：RKNN YOLO（复用 experiments/rknn_yolo 的推理与后处理）；无 NPU 时的颜色块检测（调试用）。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RKNN_DIR = ROOT / "experiments" / "rknn_yolo"

Detector = Callable[[np.ndarray], list[dict]]


def rknn_detector(model: str, labels: str, conf: float = 0.3, max_det: int = 20,
                  output_layout: str = "xyxy_score_class") -> tuple[Detector, str, Callable[[], None]]:
    sys.path.insert(0, str(RKNN_DIR))
    from infer_image import RknnYoloRunner  # noqa: E402

    runner = RknnYoloRunner(model, labels, conf=conf, max_det=max_det, output_layout=output_layout,
                            source="yuntuo-astra").load()
    return (lambda frame: runner.infer_frame(frame, color_order="bgr")), runner.model_name, runner.release


def color_blob_detector(color: str = "red", cls: str = "bottle", min_area: int = 400) -> tuple[Detector, str, Callable[[], None]]:
    """把指定颜色的连通块当作 cls 报告（没有 NPU / 模型时验证"找红瓶"链路；比赛时不要开）"""
    import cv2

    ranges = {
        "red": [((0, 120, 70), (10, 255, 255)), ((170, 120, 70), (180, 255, 255))],
        "green": [((40, 80, 60), (85, 255, 255))],
        "blue": [((95, 120, 60), (130, 255, 255))],
        "yellow": [((20, 120, 80), (35, 255, 255))],
    }[color]

    def detect(frame: np.ndarray) -> list[dict]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = None
        for lo, hi in ranges:
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
            mask = m if mask is None else cv2.bitwise_or(mask, m)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in contours:
            if cv2.contourArea(c) < min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            out.append({"class_name": cls, "confidence": 0.6, "bbox_xyxy": [x, y, x + w, y + h]})
        return out

    return detect, f"color-blob-{color}", (lambda: None)
