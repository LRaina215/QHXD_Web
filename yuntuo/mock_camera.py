"""mock_fpga 的模拟相机输出：把虚拟物体投影成检测框，上送后端 detection_status，并渲染一张合成画面
（网页"视觉感知"窗口用；画面左上角标注 SIMULATION）。需要 Pillow；没有则只上送检测结果。"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

W, H, HFOV = 640, 480, 60.0
FX = W / 2 / math.tan(math.radians(HFOV) / 2)
CAM_Z = 0.30
SIZES = {"bottle": (0.07, 0.22), "person": (0.45, 1.70), "cup": (0.08, 0.10)}
RGB = {"red": (220, 40, 50), "blue": (40, 90, 220), "green": (40, 190, 90), None: (200, 170, 120)}


def project(obj: dict) -> list[float] | None:
    x, y = obj["x"], obj["y"]
    if x <= 0.2:
        return None
    w, h = SIZES.get(obj["cls"], (0.2, 0.3))
    u = W / 2 - FX * y / x
    top = H / 2 - FX * (h - CAM_Z) / x
    bottom = H / 2 + FX * CAM_Z / x
    half = FX * w / 2 / x
    box = [max(0.0, u - half), max(0.0, top), min(W - 1.0, u + half), min(H - 1.0, bottom)]
    return box if box[2] > box[0] and box[3] > box[1] else None


def detection_status(objects: list[dict]) -> dict:
    out = []
    for o in objects:
        box = project(o)
        if box is None:
            continue
        o["bbox"] = box
        out.append({"class_name": o["cls"], "confidence": o["conf"], "bbox_xyxy": [round(v, 1) for v in box],
                    "current_frame": True, "track_id": o["track_id"], "color": o["color"],
                    "position_body_m": [o["x"], o["y"], o["z"]], "distance_m": round(math.hypot(o["x"], o["y"]), 3)})
    return {"enabled": True, "source": "mock_camera", "model_name": "simulation", "frame_id": "camera_front",
            "timestamp": datetime.now(timezone.utc).isoformat(), "objects": out, "events": []}


def post_status(backend: str, status: dict) -> None:
    body = json.dumps({"detection_status": status}).encode("utf-8")
    req = request.Request(backend.rstrip("/") + "/api/internal/perception/detection_status", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.build_opener(request.ProxyHandler({})).open(req, timeout=1.0) as resp:
            resp.read()
    except Exception:
        pass


def render(objects: list[dict], path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for yy in range(H):
        t = yy / H
        c = (int(18 + 30 * t), int(26 + 40 * t), int(34 + 36 * t)) if yy < H / 2 else (int(46 + 40 * t), int(52 + 34 * t), int(50 + 20 * t))
        d.line([(0, yy), (W, yy)], fill=c)
    for o in sorted(objects, key=lambda o: -o["x"]):
        box = o.get("bbox")
        if not box:
            continue
        d.rectangle(box, fill=RGB.get(o["color"], RGB[None]))
    for o in objects:
        box = o.get("bbox")
        if not box:
            continue
        col = (255, 77, 94) if o["color"] == "red" else (47, 224, 196)
        d.rectangle(box, outline=col, width=2)
        d.text((box[0] + 2, max(0, box[1] - 12)), f"{o['cls']}#{o['track_id']} {math.hypot(o['x'], o['y']):.2f}m", fill=col)
    d.rectangle([W / 2 - 52, 8, W / 2 + 52, 26], fill=(0, 0, 0))
    d.text((W / 2 - 46, 11), "SIMULATION", fill=(255, 181, 71))
    tmp = path.with_suffix(".tmp.jpg")
    img.save(tmp, quality=80)
    os.replace(tmp, path)
