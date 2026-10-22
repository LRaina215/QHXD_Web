"""感知节点：python -m yuntuo.perception.node

  --source astra（缺省）| replay:目录      --detector rknn（缺省）| blob:red
每帧：检测 -> 颜色 -> 三维定位 -> 跟踪；有三维位置的目标以 UDP JSON 发给 fpga_bridge（127.0.0.1:9102，由它筛选
后转成 NV TARGET）；按 --status-hz 向后端上送 detection_status，按 --save-hz 写带框的最新帧（网页 MJPEG / 截图用）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from urllib import request

from yuntuo.perception.detectors import RKNN_DIR, color_blob_detector, rknn_detector
from yuntuo.perception.geometry import Mount
from yuntuo.perception.pipeline import Pipeline, PipelineConfig, bridge_message, detection_status

log = logging.getLogger("perception")


class LatestPoster(threading.Thread):
    def __init__(self, url: str) -> None:
        super().__init__(daemon=True, name="status-poster")
        self.url, self.cond, self.item = url, threading.Condition(), None
        self.opener = request.build_opener(request.ProxyHandler({}))

    def put(self, payload: dict) -> None:
        with self.cond:
            self.item = payload
            self.cond.notify()

    def run(self) -> None:
        while True:
            with self.cond:
                while self.item is None:
                    self.cond.wait()
                payload, self.item = self.item, None
            body = json.dumps({"detection_status": payload}, ensure_ascii=False).encode("utf-8")
            req = request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with self.opener.open(req, timeout=1.5) as resp:
                    resp.read()
            except Exception as exc:
                log.debug("上送 detection_status 失败：%s", exc)


def save_annotated(frame, dets: list[dict], path: Path) -> None:
    import cv2

    img = frame.copy()
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d["bbox"])
        color = (0, 0, 255) if d.get("color") == "red" else (0, 200, 255)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{d['cls']}#{d.get('track_id', 0)}"
        if d.get("color"):
            text += f" {d['color']}"
        if d.get("position"):
            text += f" {((d['position'][0] ** 2 + d['position'][1] ** 2) ** 0.5):.2f}m"
        cv2.putText(img, text, (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    tmp = path.with_suffix(".tmp.jpg")
    cv2.imwrite(str(tmp), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    os.replace(tmp, path)


def parse_mount(text: str) -> Mount:
    x, y, z, pitch, yaw, roll = (float(v) for v in text.split(","))
    return Mount(x, y, z, pitch, yaw, roll)


def reset_thread_nice(value: int) -> int:
    """Linux 的 nice 是按线程的：逐个把本进程线程的 nice 调到 value（只调低优先级，不需要特权），返回改动数。"""
    task_dir = Path("/proc/self/task")
    if not task_dir.is_dir():
        return 0
    changed = 0
    for entry in task_dir.iterdir():
        try:
            tid = int(entry.name)
            if os.getpriority(os.PRIO_PROCESS, tid) < value:
                os.setpriority(os.PRIO_PROCESS, tid, value)
                changed += 1
        except (ValueError, OSError):
            continue
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=os.getenv("YUNTUO_CAMERA_SOURCE", "astra"))
    ap.add_argument("--color-device", default=os.getenv("YUNTUO_COLOR_DEVICE", "/dev/video0"))
    default_redist = "/opt/OpenNI2/Redist" if Path("/opt/OpenNI2/Redist/libOpenNI2.so").exists() else None
    # 系统自带 libopenni2 不认 Orbbec 设备，缺省用 scripts/install_orbbec_openni2.sh 装的那份
    ap.add_argument("--openni-redist", default=os.getenv("OPENNI2_REDIST") or default_redist)
    ap.add_argument("--no-depth", action="store_true")
    ap.add_argument("--detector", default=os.getenv("YUNTUO_DETECTOR", "rknn"))
    ap.add_argument("--model", default=str(RKNN_DIR / "models/yolo26n_fp32.rknn"))
    ap.add_argument("--labels", default=str(RKNN_DIR / "models/labels.txt"))
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--mount", default=os.getenv("YUNTUO_CAMERA_MOUNT", "0.20,0,0.30,10,0,0"),
                    help="相机在机身系的 x,y,z(m),pitch,yaw,roll(度，pitch 向下为正)")
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--bridge-udp", default=os.getenv("YUNTUO_PERCEPTION_UDP", "127.0.0.1:9102"))
    ap.add_argument("--backend", default=os.getenv("YUNTUO_BACKEND_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--status-hz", type=float, default=2.0)
    ap.add_argument("--save-latest", default=str(RKNN_DIR / "outputs/latest_camera_detection.jpg"))
    ap.add_argument("--save-hz", type=float, default=5.0)
    ap.add_argument("--nice", type=int, default=int(os.getenv("YUNTUO_PERCEPTION_NICE", "0")),
                    help="librknnrt 初始化时会把所有线程调到 nice -19，压过板上大模型 / 语音合成 / 后端；这里调回该值")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.detector.startswith("blob"):
        detect, model_name, release = color_blob_detector(args.detector.partition(":")[2] or "red")
    else:
        detect, model_name, release = rknn_detector(args.model, args.labels, conf=min(args.conf, 0.3))
    if args.source.startswith("replay:"):
        from yuntuo.perception.sources import ReplaySource
        source = ReplaySource(args.source.partition(":")[2], fps=args.fps)
    else:
        from yuntuo.perception.sources import AstraSource
        source = AstraSource(args.color_device, openni_redist=args.openni_redist, depth_enabled=not args.no_depth)
    pipeline = Pipeline(detect, PipelineConfig(mount=parse_mount(args.mount), min_conf=args.conf))
    host, _, port = args.bridge_udp.rpartition(":")
    bridge_addr = (host or "127.0.0.1", int(port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    poster = LatestPoster(args.backend.rstrip("/") + "/api/internal/perception/detection_status")
    poster.start()
    save_path = Path(args.save_latest)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    seq, next_status, next_save, period = 0, 0.0, 0.0, 1.0 / max(1.0, args.fps)
    changed = reset_thread_nice(args.nice)
    log.info("感知节点启动：来源 %s，检测器 %s，发往 fpga_bridge %s（%d 个线程 nice 调回 %d）",
             args.source, model_name, bridge_addr, changed, args.nice)
    next_nice = time.monotonic() + 5.0
    try:
        while True:
            t0 = time.monotonic()
            frame = source.read()
            if frame is None:
                continue
            seq += 1
            dets = pipeline.process(frame)
            sock.sendto(json.dumps(bridge_message(dets, frame, seq)).encode("utf-8"), bridge_addr)
            now = time.monotonic()
            if now >= next_nice:                      # 运行库后建的线程同样会被调高优先级
                next_nice = now + 5.0
                reset_thread_nice(args.nice)
            if now >= next_status:
                next_status = now + 1.0 / args.status_hz
                poster.put(detection_status(dets, model_name=model_name))
            if now >= next_save:
                next_save = now + 1.0 / args.save_hz
                save_annotated(frame.color, dets, save_path)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
