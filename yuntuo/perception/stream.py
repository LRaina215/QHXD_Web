"""低延迟视频：带检测框的画面经 RK MPP 硬件 H.264 编码，RTMP 推到云端 MediaMTX（网页走 WebRTC / HLS 播放）。

视频帧率与检测帧率分开：推流线程按 --stream-fps 取相机最新一帧，画上最近一次检测的框再编码。
没有找物 / 跟随任务时检测只有 5 fps，视频照样流畅；框最多落后一个检测周期，检测结果过旧（> max_det_age_s）就不画。
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Callable

from yuntuo.perception.detectors import RKNN_DIR

log = logging.getLogger("perception.stream")

RED = (0, 0, 255)
AMBER = (0, 200, 255)


def annotate(frame: Any, dets: list[dict]) -> Any:
    """在副本上画框与标签（目标类别#跟踪号、颜色、水平距离），网页截图与视频共用这一种画法。"""
    import cv2

    img = frame.copy()
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d["bbox"])
        color = RED if d.get("color") == "red" else AMBER
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{d['cls']}#{d.get('track_id', 0)}"
        if d.get("color"):
            text += f" {d['color']}"
        if d.get("position"):
            text += f" {((d['position'][0] ** 2 + d['position'][1] ** 2) ** 0.5):.2f}m"
        cv2.putText(img, text, (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return img


class AnnotatedStream(threading.Thread):
    """peek() -> (最新 BGR 帧或 None, 采集时刻 monotonic)；publisher 需有 submit(frame, color_order=...) 与 stats。"""

    def __init__(self, peek: Callable[[], tuple[Any, float]], publisher: Any, fps: float = 15.0,
                 max_det_age_s: float = 0.6) -> None:
        super().__init__(daemon=True, name="annotated-stream")
        self.peek, self.publisher = peek, publisher
        self.period = 1.0 / max(1.0, fps)
        self.max_det_age_s = max_det_age_s
        self._lock = threading.Lock()
        self._dets: list[dict] = []
        self._det_stamp = 0.0
        self._stop = threading.Event()
        self.frames = 0

    def update(self, dets: list[dict], stamp: float) -> None:
        with self._lock:
            self._dets, self._det_stamp = dets, stamp

    def current_dets(self, now: float) -> list[dict]:
        with self._lock:
            return self._dets if now - self._det_stamp <= self.max_det_age_s else []

    def step(self, last_stamp: float) -> float:
        """送一帧（有新画面才送），返回本次用的采集时刻。拆出来便于测试。"""
        frame, stamp = self.peek()
        if frame is None or stamp <= last_stamp:
            return last_stamp
        self.publisher.submit(annotate(frame, self.current_dets(time.monotonic())), color_order="bgr")
        self.frames += 1
        return stamp

    def run(self) -> None:
        last_stamp = 0.0
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                last_stamp = self.step(last_stamp)
            except Exception as exc:  # noqa: BLE001  推流出错不能拖垮感知主循环
                log.warning("推流取帧失败：%s", exc)
            self._stop.wait(max(0.0, self.period - (time.monotonic() - t0)))

    def stop(self) -> None:
        self._stop.set()


def make_publisher(url: str, fps: float, width: int, height: int, bitrate: int) -> Any:
    """复用 experiments/rknn_yolo/h264_stream_publisher.py（GStreamer appsrc → mpph264enc → flvmux → rtmpsink）。"""
    if str(RKNN_DIR) not in sys.path:
        sys.path.insert(0, str(RKNN_DIR))
    from h264_stream_publisher import H264StreamPublisher, StreamPublisherConfig, redact_stream_url  # noqa: E402

    config = StreamPublisherConfig(url=url, fps=fps, width=width, height=height, bitrate=bitrate, queue_size=1)
    publisher = H264StreamPublisher(config)
    publisher.redacted_url = redact_stream_url(url)
    return publisher
