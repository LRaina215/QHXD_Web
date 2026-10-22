"""单帧处理：检测 -> 颜色 -> 三维定位 -> 跟踪，输出给 fpga_bridge 的检测消息与给后端的 detection_status。"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

from yuntuo.perception.color import dominant_color
from yuntuo.perception.geometry import Intrinsics, Mount, locate
from yuntuo.perception.sources import RgbdFrame
from yuntuo.perception.tracker import Tracker

# 只对这些类别算颜色（人的衣服颜色意义不大且易误导）
COLOR_CLASSES = {"bottle", "cup", "sports ball", "backpack", "chair", "box"}


def color_bbox_to_depth(bbox: list[float], kc: Intrinsics, kd: Intrinsics) -> list[float]:
    """未配准时：按视角把彩色像素框映射到深度像素框（同一光线方向）"""
    def m(u: float, v: float) -> tuple[float, float]:
        return kd.cx + kd.fx * (u - kc.cx) / kc.fx, kd.cy + kd.fy * (v - kc.cy) / kc.fy

    x1, y1 = m(bbox[0], bbox[1])
    x2, y2 = m(bbox[2], bbox[3])
    return [x1, y1, x2, y2]


@dataclass
class PipelineConfig:
    mount: Mount = field(default_factory=Mount)
    min_conf: float = 0.35
    max_range_m: float = 6.0
    classes: set[str] | None = None          # None = 全部类别


class Pipeline:
    def __init__(self, detect: Callable[[np.ndarray], list[dict]], cfg: PipelineConfig | None = None) -> None:
        self.detect = detect                  # BGR 图 -> [{class_name, confidence, bbox_xyxy}]
        self.cfg = cfg or PipelineConfig()
        self.tracker = Tracker()

    def process(self, frame: RgbdFrame) -> list[dict]:
        raw = self.detect(frame.color)
        dets = []
        for item in raw:
            cls = str(item.get("class_name", "unknown"))
            conf = float(item.get("confidence", 0.0))
            if conf < self.cfg.min_conf or (self.cfg.classes and cls not in self.cfg.classes):
                continue
            bbox = [float(v) for v in item["bbox_xyxy"][:4]]
            det: dict[str, Any] = {"cls": cls, "conf": round(conf, 3), "bbox": bbox, "color": None, "position": None}
            if cls in COLOR_CLASSES:
                det["color"], _ = dominant_color(frame.color, bbox)
                if det["color"] == "other":
                    det["color"] = None
            if frame.depth_mm is not None:
                dbox = bbox if frame.registered else color_bbox_to_depth(bbox, frame.k_color, frame.k_depth)
                k = frame.k_color if frame.registered else frame.k_depth
                p = locate(frame.depth_mm, dbox, k, self.cfg.mount)
                if p is not None and math.hypot(p[0], p[1]) <= self.cfg.max_range_m:
                    det["position"] = [round(float(v), 3) for v in p]
            dets.append(det)
        return self.tracker.update(dets, frame.stamp_mono)


def bridge_message(dets: list[dict], frame: RgbdFrame, seq: int, source: str = "astra") -> dict:
    """fpga_bridge 感知端口的消息（只含有三维位置的目标）"""
    objects = []
    for d in dets:
        if d.get("position") is None:
            continue
        x, y, z = d["position"]
        objects.append({"cls": d["cls"], "color": d.get("color"), "conf": d["conf"], "track_id": d.get("track_id", 0),
                        "x": x, "y": y, "z": z, "bbox": [round(v, 1) for v in d["bbox"]]})
    age = time.monotonic() - frame.stamp_mono
    return {"type": "detections", "source": source, "frame_seq": seq, "stamp_mono": frame.stamp_mono,
            "stamp_wall": time.time() - age, "objects": objects}


def detection_status(dets: list[dict], *, model_name: str, frame_id: str = "camera_front",
                     source: str = "yuntuo-astra") -> dict:
    """后端 /api/internal/perception/detection_status 的 DetectionStatus"""
    objects = []
    for d in dets:
        obj: dict[str, Any] = {"class_name": d["cls"], "confidence": d["conf"], "bbox_xyxy": d["bbox"],
                               "current_frame": True, "track_id": d.get("track_id"), "color": d.get("color")}
        if d.get("position") is not None:
            obj["position_body_m"] = d["position"]
            obj["distance_m"] = round(math.hypot(d["position"][0], d["position"][1]), 3)
        objects.append(obj)
    return {"enabled": True, "source": source, "model_name": model_name, "frame_id": frame_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), "objects": objects, "events": []}
