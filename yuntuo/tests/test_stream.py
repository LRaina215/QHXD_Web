"""推流线程：按相机最新帧送编码器、画上最近的检测框、检测过旧不画、同一帧不重复送。"""
import numpy as np
import pytest

pytest.importorskip("cv2")

from yuntuo.perception.stream import AnnotatedStream  # noqa: E402


class FakePublisher:
    def __init__(self):
        self.frames = []

    def submit(self, frame, *, color_order):
        self.frames.append((frame, color_order))


def test_stream_draws_recent_boxes_on_newest_frame_only_once(monkeypatch):
    frame = np.zeros((480, 640, 3), np.uint8)
    latest = {"frame": frame, "stamp": 10.0}
    pub = FakePublisher()
    s = AnnotatedStream(lambda: (latest["frame"], latest["stamp"]), pub, fps=15, max_det_age_s=0.6)
    now = {"t": 100.0}
    monkeypatch.setattr("yuntuo.perception.stream.time.monotonic", lambda: now["t"])
    s.update([{"bbox": [100, 100, 200, 200], "cls": "bottle", "track_id": 3, "color": "red"}], 99.9)

    last = s.step(0.0)
    assert last == 10.0 and len(pub.frames) == 1
    img, order = pub.frames[0]
    assert order == "bgr" and img[100, 150].tolist() == [0, 0, 255]   # 红色框上沿
    assert frame.sum() == 0                                             # 原帧不被改

    assert s.step(last) == 10.0 and len(pub.frames) == 1                 # 没有新画面不送

    latest["stamp"] = 10.1
    now["t"] = 101.0                                                    # 检测已过去 1.1 s，不再画框
    s.step(last)
    assert len(pub.frames) == 2 and pub.frames[1][0].sum() == 0
