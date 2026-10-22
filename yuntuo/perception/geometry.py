"""深度图 + 检测框 -> 机身系三维位置。

坐标系：相机光学系 x 右、y 下、z 前；机身系（与导航一致）x 前、y 左、z 上，原点在导航定义的机身中心。
安装参数 Mount：相机光心在机身系的位置（m）与姿态（pitch 向下为正，yaw 向左为正，roll 向右倾为正）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def scaled(self, width: int, height: int) -> "Intrinsics":
        sx, sy = width / self.width, height / self.height
        return Intrinsics(self.fx * sx, self.fy * sy, (self.cx + 0.5) * sx - 0.5, (self.cy + 0.5) * sy - 0.5,
                          width, height)

    @classmethod
    def from_fov(cls, width: int, height: int, hfov_deg: float, vfov_deg: float) -> "Intrinsics":
        fx = width / 2 / math.tan(math.radians(hfov_deg) / 2)
        fy = height / 2 / math.tan(math.radians(vfov_deg) / 2)
        return cls(fx, fy, (width - 1) / 2, (height - 1) / 2, width, height)


# Astra Pro Plus 深度（IR）640×480 出厂标定，2026-10-22 实机读出；对应视场约 58.1° × 45.3°
ASTRA_DEPTH_640 = Intrinsics(575.904, 575.904, 316.898, 244.005, 640, 480)


@dataclass(frozen=True)
class Mount:
    x: float = 0.20
    y: float = 0.0
    z: float = 0.30
    pitch_deg: float = 10.0
    yaw_deg: float = 0.0
    roll_deg: float = 0.0

    def rotation(self) -> np.ndarray:
        """光学系 -> 机身系的旋转矩阵"""
        base = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
        p, yw, r = (math.radians(v) for v in (self.pitch_deg, self.yaw_deg, self.roll_deg))
        rz = np.array([[math.cos(yw), -math.sin(yw), 0], [math.sin(yw), math.cos(yw), 0], [0, 0, 1]])
        ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
        rx = np.array([[1, 0, 0], [0, math.cos(r), -math.sin(r)], [0, math.sin(r), math.cos(r)]])
        return rz @ ry @ rx @ base

    def to_body(self, p_optical: np.ndarray) -> np.ndarray:
        return self.rotation() @ np.asarray(p_optical, dtype=float) + np.array([self.x, self.y, self.z])


def scale_bbox(bbox: list[float], from_wh: tuple[int, int], to_wh: tuple[int, int]) -> list[float]:
    sx, sy = to_wh[0] / from_wh[0], to_wh[1] / from_wh[1]
    x1, y1, x2, y2 = bbox
    return [x1 * sx, y1 * sy, x2 * sx, y2 * sy]


def bbox_depth_m(depth_mm: np.ndarray, bbox: list[float], *, shrink: float = 0.5, min_mm: int = 300,
                 max_mm: int = 6000, min_valid: int = 12, fg_band_mm: int = 250) -> float | None:
    """框中心区域的前景深度：取有效像素的 10% 分位作前景起点，前景带内取中位数（抗背景与空洞）"""
    h, w = depth_mm.shape[:2]
    x1, y1, x2, y2 = bbox
    cx, cy, hw, hh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * shrink / 2, (y2 - y1) * shrink / 2
    xa, xb = max(0, int(cx - hw)), min(w, int(math.ceil(cx + hw)) + 1)
    ya, yb = max(0, int(cy - hh)), min(h, int(math.ceil(cy + hh)) + 1)
    if xb <= xa or yb <= ya:
        return None
    region = depth_mm[ya:yb, xa:xb].astype(np.int32).ravel()
    valid = region[(region >= min_mm) & (region <= max_mm)]
    if valid.size < min_valid:
        return None
    near = np.percentile(valid, 10)
    fg = valid[valid <= near + fg_band_mm]
    return float(np.median(fg)) / 1000.0


def pixel_to_optical(u: float, v: float, z_m: float, k: Intrinsics) -> np.ndarray:
    return np.array([(u - k.cx) / k.fx * z_m, (v - k.cy) / k.fy * z_m, z_m])


def locate(depth_mm: np.ndarray, bbox_depth_px: list[float], k: Intrinsics, mount: Mount) -> np.ndarray | None:
    """检测框（已换算到深度图像素）-> 机身系 [x, y, z]（m）"""
    z = bbox_depth_m(depth_mm, bbox_depth_px)
    if z is None:
        return None
    u = (bbox_depth_px[0] + bbox_depth_px[2]) / 2
    v = (bbox_depth_px[1] + bbox_depth_px[3]) / 2
    return mount.to_body(pixel_to_optical(u, v, z, k))
