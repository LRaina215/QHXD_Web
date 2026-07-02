import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera_detect_service import CameraSource, LatestFrameCapture


class FakeCamera(CameraSource):
    color_order = "rgb"

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.read_count = 0
        self.fail_after = fail_after
        self.released = False

    def read(self):
        self.read_count += 1
        if self.fail_after is not None and self.read_count > self.fail_after:
            return False, None
        return True, np.full((2, 2, 3), self.read_count, dtype=np.uint8)

    def release(self) -> None:
        self.released = True


class FakePublisher:
    def __init__(self) -> None:
        self.frames = []

    def submit(self, frame, *, color_order: str) -> None:
        self.frames.append((int(frame[0, 0, 0]), color_order))


class LatestFrameCaptureTest(unittest.TestCase):
    def test_capture_publishes_every_acquired_frame_and_exposes_latest(self) -> None:
        camera = FakeCamera()
        publisher = FakePublisher()
        capture = LatestFrameCapture(camera, fps=50, read_fail_limit=2, stream_publisher=publisher)
        try:
            first = capture.wait_for_frame(0, 0.5)
            self.assertIsNotNone(first)
            time.sleep(0.06)
            latest = capture.wait_for_frame(first[0], 0.5)
            self.assertIsNotNone(latest)
            self.assertGreater(latest[0], first[0])
            self.assertGreaterEqual(len(publisher.frames), latest[0])
            self.assertTrue(all(order == "rgb" for _, order in publisher.frames))
        finally:
            capture.close()
        self.assertTrue(camera.released)

    def test_capture_reports_terminal_read_failure(self) -> None:
        camera = FakeCamera(fail_after=1)
        capture = LatestFrameCapture(camera, fps=100, read_fail_limit=2, stream_publisher=None)
        try:
            first = capture.wait_for_frame(0, 0.5)
            self.assertIsNotNone(first)
            deadline = time.monotonic() + 0.5
            while not capture.failed and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(capture.failed)
            self.assertIsNone(capture.wait_for_frame(first[0], 0.01))
        finally:
            capture.close()


if __name__ == "__main__":
    unittest.main()
