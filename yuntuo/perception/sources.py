"""RGB-D 帧来源。

  astra    Orbbec Astra Pro Plus：彩色走 UVC（OpenCV V4L2），深度走 OpenNI2（pip 包 openni + Orbbec OpenNI2 SDK 的
           libOpenNI2.so）。两路各自后台读最新帧；时间戳取彩色帧到达时刻。
  replay   目录回放：color_XXXX.jpg/png + depth_XXXX.npy（uint16 mm），离线调参与回归用。
深度与彩色未硬件配准时，检测框按两路内参的视角关系映射到深度图（忽略约 2.5 cm 的基线，框中心区取前景深度可容忍）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from yuntuo.perception.geometry import ASTRA_DEPTH_640, Intrinsics

# Astra Pro Plus 出厂标定（640×480 基准；2026-10-22 从实机 OBEXTENSION_ID_CAM_PARAMS 读出）。
# 运行时优先读设备自己的标定，读不到才用这组值。彩色 fx 543.5 → 水平视场约 60.9°。
ASTRA_COLOR_640 = Intrinsics(543.467, 543.467, 316.355, 242.649, 640, 480)
OB_PROP_CAM_PARAMS = 14   # Orbbec OpenNI2 扩展：OBCameraParams（l = 深度/IR，r = 彩色，fx fy cx cy）


@dataclass
class RgbdFrame:
    color: np.ndarray                 # BGR uint8
    depth_mm: np.ndarray | None       # uint16
    stamp_mono: float
    k_color: Intrinsics
    k_depth: Intrinsics
    registered: bool = False          # True：深度已配准到彩色像素


class _LatestReader(threading.Thread):
    def __init__(self, read_fn, name: str) -> None:
        super().__init__(daemon=True, name=name)
        self.read_fn = read_fn
        self.lock = threading.Lock()
        self.value: Any = None
        self.stamp = 0.0
        self.error: str | None = None
        self.running = True

    def run(self) -> None:
        while self.running:
            try:
                value = self.read_fn()
            except Exception as exc:  # 设备拔出等
                self.error = str(exc)
                time.sleep(0.5)
                continue
            if value is not None:
                with self.lock:
                    self.value, self.stamp = value, time.monotonic()

    def latest(self) -> tuple[Any, float]:
        with self.lock:
            return self.value, self.stamp


class AstraSource:
    def __init__(self, color_device: str = "/dev/video0", width: int = 640, height: int = 480, fps: int = 30,
                 openni_redist: str | None = None, registration: bool = True, depth_enabled: bool = True) -> None:
        import cv2

        self.cap = cv2.VideoCapture(color_device, cv2.CAP_V4L2) if color_device.startswith("/dev/") \
            else cv2.VideoCapture(int(color_device) if color_device.isdigit() else color_device)
        # MJPG：同分辨率下实测 20 fps，YUYV 只有约 12 fps（USB 2.0 带宽）
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        if not self.cap.isOpened():
            raise RuntimeError(f"彩色相机 {color_device} 打不开")
        self.width, self.height = width, height
        self.k_color = ASTRA_COLOR_640.scaled(width, height)
        self.k_depth = ASTRA_DEPTH_640
        self.calibration_source = "default"
        self.registered = False
        self.color_reader = _LatestReader(self._read_color, "astra-color")
        self.depth_reader = None
        if depth_enabled:
            self._open_depth(openni_redist, registration)
        self.color_reader.start()

    def _read_color(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def _open_depth(self, redist: str | None, registration: bool) -> None:
        from openni import _openni2 as c_api
        from openni import openni2

        openni2.initialize(redist) if redist else openni2.initialize()
        self.device = openni2.Device.open_any()
        self.depth = self.device.create_depth_stream()
        self.depth.set_video_mode(c_api.OniVideoMode(
            pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_1_MM, resolutionX=640, resolutionY=480, fps=30))
        self.depth.set_mirroring_enabled(False)
        self._read_factory_calibration(c_api)
        if registration:
            try:
                self.device.set_image_registration_mode(openni2.IMAGE_REGISTRATION_DEPTH_TO_COLOR)
                self.registered = True
            except Exception:
                self.registered = False
        self.depth.start()

        def read_depth():
            f = self.depth.read_frame()
            return np.frombuffer(f.get_buffer_as_uint16(), dtype=np.uint16).reshape(f.height, f.width).copy()

        self.depth_reader = _LatestReader(read_depth, "astra-depth")
        self.depth_reader.start()

    def _read_factory_calibration(self, c_api) -> None:
        import ctypes

        class OBCameraParams(ctypes.Structure):
            _fields_ = [("l_intr_p", ctypes.c_float * 4), ("r_intr_p", ctypes.c_float * 4),
                        ("r2l_r", ctypes.c_float * 9), ("r2l_t", ctypes.c_float * 3),
                        ("l_k", ctypes.c_float * 5), ("r_k", ctypes.c_float * 5)]

        params = OBCameraParams()
        size = ctypes.c_int(ctypes.sizeof(params))
        try:
            rc = c_api.oniDeviceGetProperty(self.device._handle, OB_PROP_CAM_PARAMS, ctypes.byref(params),
                                            ctypes.byref(size))
        except Exception:
            return
        if rc != c_api.OniStatus.ONI_STATUS_OK or params.r_intr_p[0] <= 0 or params.l_intr_p[0] <= 0:
            return
        self.k_color = Intrinsics(*params.r_intr_p, 640, 480).scaled(self.width, self.height)
        self.k_depth = Intrinsics(*params.l_intr_p, 640, 480)
        self.calibration_source = "factory"

    def read(self, timeout: float = 1.0) -> RgbdFrame | None:
        deadline = time.monotonic() + timeout
        last_stamp = getattr(self, "_last_stamp", 0.0)
        while time.monotonic() < deadline:
            color, stamp = self.color_reader.latest()
            if color is not None and stamp > last_stamp:
                self._last_stamp = stamp
                depth, dstamp = self.depth_reader.latest() if self.depth_reader else (None, 0.0)
                if depth is not None and abs(dstamp - stamp) > 0.2:
                    depth = None
                return RgbdFrame(color, depth, stamp, self.k_color, self.k_depth, self.registered)
            time.sleep(0.005)
        return None

    def close(self) -> None:
        self.color_reader.running = False
        if self.depth_reader is not None:
            self.depth_reader.running = False
        self.cap.release()


class ReplaySource:
    def __init__(self, directory: str, fps: float = 10.0, loop: bool = True) -> None:
        self.dir = Path(directory)
        self.colors = sorted(p for p in self.dir.iterdir() if p.stem.startswith("color_") and p.suffix in {".jpg", ".png"})
        if not self.colors:
            raise RuntimeError(f"{directory} 下没有 color_*.jpg/png")
        self.i, self.period, self.loop, self.next_at = 0, 1.0 / fps, loop, 0.0

    def read(self, timeout: float = 1.0) -> RgbdFrame | None:
        import cv2

        if self.i >= len(self.colors):
            if not self.loop:
                return None
            self.i = 0
        time.sleep(max(0.0, self.next_at - time.monotonic()))
        self.next_at = time.monotonic() + self.period
        cp = self.colors[self.i]
        self.i += 1
        color = cv2.imread(str(cp))
        dp = cp.with_name(cp.stem.replace("color_", "depth_") + ".npy")
        depth = np.load(dp) if dp.exists() else None
        h, w = color.shape[:2]
        k = ASTRA_COLOR_640.scaled(w, h)
        return RgbdFrame(color, depth, time.monotonic(), k, k if depth is not None else ASTRA_DEPTH_640, True)

    def close(self) -> None:
        pass
