from __future__ import annotations

import os
import sys
from ctypes import POINTER, byref, c_ubyte, cast, memset, sizeof
from pathlib import Path
from typing import Any

MVS_IMPORT_PATH = Path(os.getenv("HIK_MVS_IMPORT_PATH", "/opt/MVS/Samples/aarch64/Python/MvImport"))
MVS_COMMON_RUNENV = Path(os.getenv("MVCAM_COMMON_RUNENV", "/opt/MVS/lib"))


def _ensure_mvs_import_path() -> None:
    if str(MVS_IMPORT_PATH) not in sys.path:
        sys.path.append(str(MVS_IMPORT_PATH))
    os.environ.setdefault("MVCAM_SDK_PATH", "/opt/MVS")
    os.environ.setdefault("MVCAM_COMMON_RUNENV", str(MVS_COMMON_RUNENV))
    os.environ.setdefault("MVCAM_SOFTWARE_LIBENV", str(MVS_COMMON_RUNENV))
    os.environ.setdefault("MVCAM_GENICAM_CLPROTOCOL", str(MVS_COMMON_RUNENV / "CLProtocol"))


def _decode_c_string(value: Any) -> str:
    raw = memoryview(value).tobytes().split(b"\x00", 1)[0]
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


class HikCameraSource:
    """Hikrobot/MVS SDK camera source that returns RGB numpy frames."""

    color_order = "rgb"

    def __init__(self, *, index: int = 0, serial: str | None = None, timeout_ms: int = 1000) -> None:
        self.index = index
        self.serial = serial
        self.timeout_ms = timeout_ms
        self._loaded = False
        self._opened = False
        self._grabbing = False
        self._cam = None
        self._sdk: dict[str, Any] = {}
        self.last_error = ""
        self.device_label = ""
        self._open()

    def is_opened(self) -> bool:
        return self._opened and self._grabbing and self._cam is not None

    def read(self) -> tuple[bool, Any]:
        if not self.is_opened():
            return False, None
        sdk = self._sdk
        frame = sdk["MV_FRAME_OUT"]()
        memset(byref(frame), 0, sizeof(frame))
        ret = self._cam.MV_CC_GetImageBuffer(frame, self.timeout_ms)
        if ret != 0 or not frame.pBufAddr:
            self.last_error = f"Hik camera get image buffer failed ret=0x{ret:x}"
            return False, None
        try:
            image = self._convert_frame_to_rgb(frame)
            return True, image
        finally:
            self._cam.MV_CC_FreeImageBuffer(frame)

    def release(self) -> None:
        if self._cam is not None:
            if self._grabbing:
                try:
                    self._cam.MV_CC_StopGrabbing()
                except Exception:
                    pass
                self._grabbing = False
            if self._opened:
                try:
                    self._cam.MV_CC_CloseDevice()
                except Exception:
                    pass
                self._opened = False
            try:
                self._cam.MV_CC_DestroyHandle()
            except Exception:
                pass
            self._cam = None
        if self._loaded:
            try:
                self._sdk["MvCamera"].MV_CC_Finalize()
            except Exception:
                pass
            self._loaded = False

    def _open(self) -> None:
        try:
            self._load_sdk()
            device = self._select_device()
            if device is None:
                return
            cam = self._sdk["MvCamera"]()
            ret = cam.MV_CC_CreateHandle(device)
            if ret != 0:
                self.last_error = f"Hik camera create handle failed ret=0x{ret:x}"
                return
            self._cam = cam
            ret = cam.MV_CC_OpenDevice(self._sdk["MV_ACCESS_Exclusive"], 0)
            if ret != 0:
                self.last_error = f"Hik camera open failed ret=0x{ret:x}"
                return
            self._opened = True
            cam.MV_CC_SetEnumValue("TriggerMode", self._sdk["MV_TRIGGER_MODE_OFF"])
            ret = cam.MV_CC_StartGrabbing()
            if ret != 0:
                self.last_error = f"Hik camera start grabbing failed ret=0x{ret:x}"
                return
            self._grabbing = True
        except Exception as exc:
            self.last_error = f"Hik camera SDK error: {exc}"
            self.release()

    def _load_sdk(self) -> None:
        _ensure_mvs_import_path()
        from MvCameraControl_class import (  # type: ignore
            MV_ACCESS_Exclusive,
            MV_CC_DEVICE_INFO,
            MV_CC_DEVICE_INFO_LIST,
            MV_CC_PIXEL_CONVERT_PARAM_EX,
            MV_FRAME_OUT,
            MV_GIGE_DEVICE,
            MV_TRIGGER_MODE_OFF,
            MV_USB_DEVICE,
            MvCamera,
            PixelType_Gvsp_RGB8_Packed,
        )

        MvCamera.MV_CC_Initialize()
        self._loaded = True
        self._sdk = {
            "MV_ACCESS_Exclusive": MV_ACCESS_Exclusive,
            "MV_CC_DEVICE_INFO": MV_CC_DEVICE_INFO,
            "MV_CC_DEVICE_INFO_LIST": MV_CC_DEVICE_INFO_LIST,
            "MV_CC_PIXEL_CONVERT_PARAM_EX": MV_CC_PIXEL_CONVERT_PARAM_EX,
            "MV_FRAME_OUT": MV_FRAME_OUT,
            "MV_GIGE_DEVICE": MV_GIGE_DEVICE,
            "MV_TRIGGER_MODE_OFF": MV_TRIGGER_MODE_OFF,
            "MV_USB_DEVICE": MV_USB_DEVICE,
            "MvCamera": MvCamera,
            "PixelType_Gvsp_RGB8_Packed": PixelType_Gvsp_RGB8_Packed,
        }

    def _select_device(self):
        sdk = self._sdk
        device_list = sdk["MV_CC_DEVICE_INFO_LIST"]()
        tlayer = sdk["MV_GIGE_DEVICE"] | sdk["MV_USB_DEVICE"]
        ret = sdk["MvCamera"].MV_CC_EnumDevices(tlayer, device_list)
        if ret != 0:
            self.last_error = f"Hik camera enum failed ret=0x{ret:x}"
            return None
        if device_list.nDeviceNum == 0:
            self.last_error = "Hik camera enum found no device"
            return None

        matches = []
        discovered_labels = []
        for idx in range(device_list.nDeviceNum):
            info = cast(device_list.pDeviceInfo[idx], POINTER(sdk["MV_CC_DEVICE_INFO"])).contents
            label = self._device_label(info)
            discovered_labels.append(label or f"device[{idx}]")
            if self.serial and self.serial not in label:
                continue
            matches.append((idx, info, label))
        if not matches:
            found = ", ".join(discovered_labels) or "none"
            self.last_error = f"Hik camera serial not found: {self.serial}; discovered: {found}"
            return None
        if self.index >= len(matches):
            self.last_error = f"Hik camera index {self.index} out of range, found {len(matches)}"
            return None
        _idx, info, label = matches[self.index]
        self.device_label = label
        return info

    def _device_label(self, info) -> str:
        sdk = self._sdk
        if info.nTLayerType == sdk["MV_USB_DEVICE"]:
            model = _decode_c_string(info.SpecialInfo.stUsb3VInfo.chModelName)
            serial = _decode_c_string(info.SpecialInfo.stUsb3VInfo.chSerialNumber)
            return f"USB {model} {serial}".strip()
        model = _decode_c_string(info.SpecialInfo.stGigEInfo.chModelName)
        return f"GigE {model}".strip()

    def _convert_frame_to_rgb(self, frame):
        import numpy as np

        sdk = self._sdk
        width = int(frame.stFrameInfo.nWidth)
        height = int(frame.stFrameInfo.nHeight)
        dst_size = width * height * 3
        dst = (c_ubyte * dst_size)()
        param = sdk["MV_CC_PIXEL_CONVERT_PARAM_EX"]()
        memset(byref(param), 0, sizeof(param))
        param.nWidth = width
        param.nHeight = height
        param.pSrcData = frame.pBufAddr
        param.nSrcDataLen = frame.stFrameInfo.nFrameLen
        param.enSrcPixelType = frame.stFrameInfo.enPixelType
        param.enDstPixelType = sdk["PixelType_Gvsp_RGB8_Packed"]
        param.pDstBuffer = dst
        param.nDstBufferSize = dst_size
        ret = self._cam.MV_CC_ConvertPixelTypeEx(param)
        if ret != 0:
            raise RuntimeError(f"Hik camera pixel convert failed ret=0x{ret:x}")
        return np.frombuffer(dst, dtype=np.uint8, count=dst_size).reshape(height, width, 3).copy()
