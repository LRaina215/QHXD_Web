from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class StreamPublisherConfig:
    url: str
    fps: float = 10.0
    width: int = 1280
    height: int = 720
    bitrate: int = 1_200_000
    queue_size: int = 2
    reconnect_interval: float = 3.0

    def validate(self) -> None:
        scheme = urlsplit(self.url).scheme.lower()
        if scheme not in {"rtmp", "rtmps", "file"}:
            raise ValueError("stream_url must use rtmp://, rtmps://, or file://")
        if any(char in self.url for char in ('"', "\n", "\r")):
            raise ValueError("stream_url contains unsupported characters")
        if self.fps <= 0:
            raise ValueError("stream_fps must be greater than zero")
        if self.width < 96 or self.height < 64:
            raise ValueError("stream dimensions are below the MPP encoder minimum")
        if self.bitrate < 100_000:
            raise ValueError("stream_bitrate must be at least 100000")
        if self.queue_size not in {1, 2}:
            raise ValueError("stream_queue_size must be 1 or 2")
        if self.reconnect_interval < 0:
            raise ValueError("stream_reconnect_interval cannot be negative")


@dataclass
class StreamPublisherStats:
    submitted: int = 0
    pushed: int = 0
    dropped: int = 0
    reconnects: int = 0
    last_error: str = ""


class H264StreamPublisher:
    """Bounded RGB/BGR frame publisher backed by Rockchip MPP and GStreamer."""

    def __init__(self, config: StreamPublisherConfig) -> None:
        config.validate()
        self.config = config
        self.stats = StreamPublisherStats()
        self._frames: queue.Queue[tuple[Any, str, float] | None] = queue.Queue(maxsize=config.queue_size)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="h264-stream-publisher", daemon=True)
        self._thread.start()

    def submit(self, frame: Any, *, color_order: str) -> None:
        if self._stop.is_set():
            return
        order = color_order.upper()
        if order not in {"RGB", "BGR"}:
            raise ValueError(f"unsupported stream frame color order: {color_order}")
        item = (frame, order, time.monotonic())
        self.stats.submitted += 1
        try:
            self._frames.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._frames.get_nowait()
            self.stats.dropped += 1
        except queue.Empty:
            pass
        try:
            self._frames.put_nowait(item)
        except queue.Full:
            self.stats.dropped += 1

    def close(self, timeout: float = 5.0) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._frames.put_nowait(None)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(None)
            except queue.Full:
                pass
        self._thread.join(timeout=max(0.0, timeout))

    def _run(self) -> None:
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except Exception as exc:
            self.stats.last_error = f"GStreamer Python bindings unavailable: {exc}"
            print(self.stats.last_error, file=sys.stderr)
            return

        Gst.init(None)
        pipeline = None
        appsrc = None
        source_shape: tuple[int, int, str] | None = None
        started_at: float | None = None

        while not self._stop.is_set():
            try:
                item = self._frames.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            frame, color_order, captured_at = item
            shape = getattr(frame, "shape", None)
            if shape is None or len(shape) != 3 or int(shape[2]) < 3:
                self.stats.dropped += 1
                self.stats.last_error = f"unsupported stream frame shape: {shape}"
                continue
            height, width = int(shape[0]), int(shape[1])
            current_shape = (width, height, color_order)

            if pipeline is None or source_shape != current_shape:
                if pipeline is not None:
                    pipeline.set_state(Gst.State.NULL)
                try:
                    description = build_pipeline_description(self.config, width, height, color_order)
                    pipeline = Gst.parse_launch(description)
                    appsrc = pipeline.get_by_name("qhxd_source")
                    if appsrc is None:
                        raise RuntimeError("GStreamer pipeline has no qhxd_source appsrc")
                    state_result = pipeline.set_state(Gst.State.PLAYING)
                    if state_result == Gst.StateChangeReturn.FAILURE:
                        raise RuntimeError("GStreamer pipeline failed to enter PLAYING")
                    source_shape = current_shape
                    started_at = captured_at
                    self.stats.reconnects += 1
                    print(
                        f"H.264 stream publisher connected: target={redact_stream_url(self.config.url)}, "
                        f"input={width}x{height} {color_order}, output={self.config.width}x{self.config.height}@{self.config.fps:g}",
                        file=sys.stderr,
                    )
                except Exception as exc:
                    self.stats.last_error = str(exc)
                    print(f"H.264 stream pipeline start failed: {exc}", file=sys.stderr)
                    if pipeline is not None:
                        pipeline.set_state(Gst.State.NULL)
                    pipeline = None
                    appsrc = None
                    if self.config.reconnect_interval > 0:
                        self._stop.wait(self.config.reconnect_interval)
                    continue

            error = _pipeline_error(Gst, pipeline)
            if error:
                self.stats.last_error = error
                print(f"H.264 stream pipeline error: {error}", file=sys.stderr)
                pipeline.set_state(Gst.State.NULL)
                pipeline = None
                appsrc = None
                if self.config.reconnect_interval > 0:
                    self._stop.wait(self.config.reconnect_interval)
                continue

            try:
                import numpy as np

                packed = np.ascontiguousarray(frame[:, :, :3], dtype=np.uint8)
                payload = packed.tobytes(order="C")
                buffer = Gst.Buffer.new_wrapped(payload)
                base_time = started_at if started_at is not None else captured_at
                buffer.pts = max(0, int((captured_at - base_time) * Gst.SECOND))
                buffer.dts = buffer.pts
                buffer.duration = int(Gst.SECOND / self.config.fps)
                result = appsrc.emit("push-buffer", buffer)
                if result != Gst.FlowReturn.OK:
                    raise RuntimeError(f"appsrc push-buffer returned {result.value_nick}")
                self.stats.pushed += 1
            except Exception as exc:
                self.stats.last_error = str(exc)
                print(f"H.264 stream frame push failed: {exc}", file=sys.stderr)
                pipeline.set_state(Gst.State.NULL)
                pipeline = None
                appsrc = None

        if appsrc is not None:
            try:
                appsrc.emit("end-of-stream")
            except Exception:
                pass
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)


def build_pipeline_description(
    config: StreamPublisherConfig,
    source_width: int,
    source_height: int,
    color_order: str,
) -> str:
    config.validate()
    frame_rate = max(1, round(config.fps))
    gop = frame_rate
    source_format = color_order.upper()
    common = (
        f'appsrc name=qhxd_source is-live=true block=false format=time '
        f'caps="video/x-raw,format={source_format},width={source_width},height={source_height},framerate={frame_rate}/1" '
        f'! queue max-size-buffers={config.queue_size} max-size-bytes=0 max-size-time=0 leaky=downstream '
        f'! videoconvert ! videoscale method=0 '
        f'! video/x-raw,format=NV12,width={config.width},height={config.height},framerate={frame_rate}/1 '
        f'! mpph264enc bps={config.bitrate} bps-min={max(100_000, config.bitrate * 3 // 4)} '
        f'bps-max={config.bitrate * 5 // 4} gop={gop} rc-mode=cbr profile=baseline header-mode=each-idr '
        f'! h264parse config-interval=-1 '
    )
    parsed = urlsplit(config.url)
    if parsed.scheme.lower() in {"rtmp", "rtmps"}:
        return common + f'! flvmux streamable=true ! rtmpsink sync=false async=false location="{config.url}"'
    output_path = Path(parsed.path)
    if not output_path.is_absolute():
        raise ValueError("file stream URL must contain an absolute path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return common + f'! mpegtsmux ! filesink location="{output_path}"'


def redact_stream_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    if parsed.username:
        credentials = f"{parsed.username}:***@" if parsed.password is not None else f"{parsed.username}@"
        netloc = credentials + host
    else:
        netloc = parsed.netloc
    query = urlencode(
        [(key, "***" if key.lower() in {"pass", "password", "token"} else value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def _pipeline_error(Gst, pipeline) -> str:
    message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
    if message is None:
        return ""
    error, debug = message.parse_error()
    return f"{error.message}; {debug or 'no debug details'}"
