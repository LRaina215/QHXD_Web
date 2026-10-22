"""在 RK3588 上用 coco128 比较 RKNN 模型：mAP@0.5（简化 VOC AP）、云拓 6 类在工作阈值下的召回 / 精度、端到端耗时。
  python3 eval_coco128.py MODEL [MODEL ...] [--coco ~/models/yolo/coco128] [--conf 0.35]
用系统 python3 + rknnlite（与感知节点同一套运行时）；跑之前先停 yuntuo-perception，否则耗时会互相干扰。"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infer_image import RknnYoloRunner, _iou  # noqa: E402

LABELS = Path(__file__).resolve().parents[1] / "models" / "labels.txt"
TARGETS = {"person", "bottle", "cup", "sports ball", "chair", "backpack"}


def load_gt(img_path: str, w: int, h: int, names: list[str]) -> list[tuple[str, list[float]]]:
    lab = Path(img_path.replace("/images/", "/labels/")).with_suffix(".txt")
    out = []
    if lab.exists():
        for line in lab.read_text().splitlines():
            p = line.split()
            if len(p) == 5:
                c, cx, cy, bw, bh = int(p[0]), *map(float, p[1:])
                out.append((names[c], [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h]))
    return out


def match(dets: list[dict], gts: list) -> list[bool]:
    used = [False] * len(gts)
    hits = []
    for d in dets:
        best, bi = 0.0, -1
        for i, (cls, box) in enumerate(gts):
            if cls == d["class_name"] and not used[i]:
                iou = _iou(d["bbox_xyxy"], box)
                if iou > best:
                    best, bi = iou, i
        hit = best >= 0.5
        if hit:
            used[bi] = True
        hits.append(hit)
    return hits


def voc_ap(tp: list[int], conf: list[float], n_gt: int) -> float | None:
    if n_gt == 0:
        return None
    if not tp:
        return 0.0
    order = np.argsort(-np.asarray(conf))
    tp_arr = np.asarray(tp, dtype=float)[order]
    ctp, cfp = np.cumsum(tp_arr), np.cumsum(1 - tp_arr)
    mrec = np.concatenate(([0.0], ctp / n_gt, [1.0]))
    mpre = np.concatenate(([1.0], ctp / np.maximum(ctp + cfp, 1e-9), [0.0]))
    for i in range(mpre.size - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def evaluate(model: str, coco: Path, conf: float, names: list[str]) -> str:
    runner = RknnYoloRunner(model, LABELS, conf=0.05, max_det=100).load()
    per_cls: dict[str, dict] = {}
    tp = fp = fn = 0
    times = []
    for path in sorted(glob.glob(str(coco / "images" / "train2017" / "*.jpg"))):
        img = cv2.imread(path)
        h, w = img.shape[:2]
        t0 = time.perf_counter()
        dets = sorted(runner.infer_frame(img, color_order="bgr"), key=lambda d: -d["confidence"])
        times.append(time.perf_counter() - t0)
        gts = load_gt(path, w, h, names)
        for cls, _ in gts:
            per_cls.setdefault(cls, {"tp": [], "conf": [], "n": 0})["n"] += 1
        for d, hit in zip(dets, match(dets, gts)):
            rec = per_cls.setdefault(d["class_name"], {"tp": [], "conf": [], "n": 0})
            rec["tp"].append(int(hit))
            rec["conf"].append(d["confidence"])
        target_gts = [g for g in gts if g[0] in TARGETS]
        target_dets = [d for d in dets if d["class_name"] in TARGETS and d["confidence"] >= conf]
        hits = match(target_dets, target_gts)
        tp += sum(hits)
        fp += len(hits) - sum(hits)
        fn += len(target_gts) - sum(hits)
    runner.release()
    aps = [a for a in (voc_ap(v["tp"], v["conf"], v["n"]) for v in per_cls.values()) if a is not None]
    t = np.asarray(times[3:]) * 1000
    return (f"{Path(model).name}: mAP@0.5={np.mean(aps):.3f}；6 类 @{conf:.2f} 召回 {tp / max(tp + fn, 1):.3f} "
            f"精度 {tp / max(tp + fp, 1):.3f}；端到端 p50 {np.median(t):.1f} ms / p90 {np.percentile(t, 90):.1f} ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--coco", type=Path, default=Path.home() / "models" / "yolo" / "coco128")
    ap.add_argument("--conf", type=float, default=0.35)
    args = ap.parse_args()
    names = [line.strip() for line in LABELS.read_text(encoding="utf-8").splitlines() if line.strip()]
    for model in args.models:
        print(evaluate(model, args.coco.expanduser(), args.conf, names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
