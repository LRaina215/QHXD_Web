"""检测框内主色判定（HSV 直方图，纯 numpy，不依赖 OpenCV）。"""
from __future__ import annotations

import numpy as np

COLORS = ("red", "green", "blue", "yellow", "white", "black", "other")


def rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """rgb: (..., 3) uint8 -> h(0..360), s(0..1), v(0..1)"""
    x = rgb.astype(np.float32) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    mx, mn = x.max(-1), x.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = (60 * ((g[rm] - b[rm]) / d[rm])) % 360
    h[gm] = 60 * ((b[gm] - r[gm]) / d[gm]) + 120
    h[bm] = 60 * ((r[bm] - g[bm]) / d[bm]) + 240
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return h, s, mx


def dominant_color(image: np.ndarray, bbox: list[float], *, color_order: str = "bgr", shrink: float = 0.7,
                   max_pixels: int = 4000) -> tuple[str, float]:
    """返回 (颜色名, 占比)。彩色像素占框内 ≥ 15% 时取彩色主色（标签、瓶盖为红也算红瓶），否则按黑白判定。"""
    h_img, w_img = image.shape[:2]
    x1, y1, x2, y2 = bbox
    cx, cy, hw, hh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * shrink / 2, (y2 - y1) * shrink / 2
    xa, xb = max(0, int(cx - hw)), min(w_img, int(cx + hw) + 1)
    ya, yb = max(0, int(cy - hh)), min(h_img, int(cy + hh) + 1)
    if xb <= xa or yb <= ya:
        return "other", 0.0
    region = image[ya:yb, xa:xb].reshape(-1, 3)
    if region.shape[0] > max_pixels:
        region = region[:: region.shape[0] // max_pixels + 1]
    if color_order == "bgr":
        region = region[:, ::-1]
    h, s, v = rgb_to_hsv(region)
    n = float(region.shape[0])
    chroma = (s >= 0.35) & (v >= 0.25)
    bins = {
        "red": chroma & ((h < 20) | (h >= 330)),
        "yellow": chroma & (h >= 40) & (h < 70),
        "green": chroma & (h >= 70) & (h < 170),
        "blue": chroma & (h >= 170) & (h < 260),
    }
    n_chroma = float(chroma.sum())
    if n_chroma / n >= 0.15:
        name, mask = max(bins.items(), key=lambda kv: int(kv[1].sum()))
        share = float(mask.sum()) / n_chroma
        if share >= 0.5:
            return name, round(float(mask.sum()) / n, 3)
    black = float((v < 0.25).sum()) / n
    white = float(((s < 0.2) & (v > 0.7)).sum()) / n
    if black >= 0.5:
        return "black", round(black, 3)
    if white >= 0.5:
        return "white", round(white, 3)
    return "other", 0.0
