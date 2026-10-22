"""目标筛选：从感知检测里挑出当前任务要找 / 跟随的那个目标，转成 NV TARGET。"""
from __future__ import annotations

import math
from dataclasses import dataclass

from yuntuo.bridge.inputs import DetectionFrame

# 类别别名（语音 / 网页常用中文 -> 检测模型 COCO 英文名）
CLASS_ALIASES = {
    "水瓶": "bottle", "瓶子": "bottle", "矿泉水": "bottle", "水杯": "cup", "杯子": "cup",
    "人": "person", "行人": "person", "我": "person", "球": "sports ball", "椅子": "chair",
    "背包": "backpack", "书包": "backpack",
}
# NV TARGET.cls：沿用 COCO 下标（固件只存不用），未知 255
CLASS_CODES = {"person": 0, "sports ball": 32, "backpack": 24, "bottle": 39, "cup": 41, "chair": 56}
COLOR_ALIASES = {"红": "red", "红色": "red", "绿": "green", "绿色": "green", "蓝": "blue", "蓝色": "blue",
                 "黄": "yellow", "黄色": "yellow", "白": "white", "白色": "white", "黑": "black", "黑色": "black"}


def normalize_class(name: str) -> str:
    key = (name or "").strip().lower()
    return CLASS_ALIASES.get(key, key)


def normalize_color(color: str | None) -> str | None:
    if not color:
        return None
    key = color.strip().lower()
    return COLOR_ALIASES.get(key, key)


@dataclass
class TargetSpec:
    target_class: str
    color: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        self.target_class = normalize_class(self.target_class)
        self.color = normalize_color(self.color)
        if not self.label:
            self.label = self.target_class

    def matches(self, obj: dict) -> bool:
        if normalize_class(str(obj.get("cls", ""))) != self.target_class:
            return False
        if self.color and normalize_color(obj.get("color")) != self.color:
            return False
        return obj.get("x") is not None and obj.get("y") is not None

    @property
    def cls_code(self) -> int:
        return CLASS_CODES.get(self.target_class, 255)


@dataclass
class TargetPick:
    obj: dict
    x_m: float
    y_m: float
    z_m: float
    track_id: int
    conf: float

    @property
    def distance_m(self) -> float:
        return math.hypot(self.x_m, self.y_m)


def pick_target(frame: DetectionFrame | None, spec: TargetSpec, locked_track: int | None) -> TargetPick | None:
    """优先保持已锁定的 track_id，其次置信度高、距离近的"""
    if frame is None:
        return None
    candidates = [o for o in frame.objects if spec.matches(o)]
    if not candidates:
        return None
    if locked_track is not None:
        same = [o for o in candidates if o.get("track_id") == locked_track]
        if same:
            candidates = same
    best = max(candidates, key=lambda o: (float(o.get("conf") or 0.0) - 0.05 * math.hypot(o["x"], o["y"])))
    return TargetPick(best, float(best["x"]), float(best["y"]), float(best.get("z") or 0.0),
                      int(best.get("track_id") or 0), float(best.get("conf") or 0.0))
