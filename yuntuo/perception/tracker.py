"""轻量多目标跟踪：同类别按 IoU 贪心匹配，IoU 不够时用三维距离兜底；颜色按最近若干帧投票平滑。"""
from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    track_id: int
    cls: str
    bbox: list[float]
    last_seen: float
    position: list[float] | None = None
    hits: int = 1
    colors: deque = field(default_factory=lambda: deque(maxlen=7))

    def color(self) -> str | None:
        votes = Counter(c for c in self.colors if c)
        return votes.most_common(1)[0][0] if votes else None


class Tracker:
    def __init__(self, iou_min: float = 0.3, dist_max_m: float = 0.4, max_age_s: float = 1.0) -> None:
        self.iou_min, self.dist_max_m, self.max_age_s = iou_min, dist_max_m, max_age_s
        self.tracks: list[Track] = []
        self.next_id = 1

    def update(self, detections: list[dict], now: float) -> list[dict]:
        """detections: {cls, bbox, conf, color?, position?}；原地补 track_id 与平滑后的 color"""
        self.tracks = [t for t in self.tracks if now - t.last_seen <= self.max_age_s]
        pairs = []
        for di, det in enumerate(detections):
            for ti, tr in enumerate(self.tracks):
                if tr.cls != det["cls"]:
                    continue
                score = iou(tr.bbox, det["bbox"])
                if score < self.iou_min and tr.position is not None and det.get("position") is not None:
                    d = math.dist(tr.position[:2], det["position"][:2])
                    score = 0.29 * (1 - d / self.dist_max_m) if d < self.dist_max_m else 0.0
                if score > 0:
                    pairs.append((score, di, ti))
        used_d, used_t = set(), set()
        for score, di, ti in sorted(pairs, reverse=True):
            if di in used_d or ti in used_t:
                continue
            used_d.add(di)
            used_t.add(ti)
            self._apply(self.tracks[ti], detections[di], now)
        for di, det in enumerate(detections):
            if di not in used_d:
                tr = Track(self.next_id, det["cls"], list(det["bbox"]), now)
                self.next_id = self.next_id % 65535 + 1
                self.tracks.append(tr)
                self._apply(tr, det, now, new=True)
        return detections

    @staticmethod
    def _apply(tr: Track, det: dict, now: float, new: bool = False) -> None:
        if not new:
            tr.hits += 1
        tr.bbox, tr.last_seen = list(det["bbox"]), now
        if det.get("position") is not None:
            tr.position = list(det["position"])
        tr.colors.append(det.get("color"))
        det["track_id"] = tr.track_id
        det["color"] = tr.color()
        det["hits"] = tr.hits
