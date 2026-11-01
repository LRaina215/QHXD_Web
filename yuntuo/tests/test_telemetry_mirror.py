"""The optional mapping recorder must not change or interrupt control feedback."""
import socket
import struct

from yuntuo.bridge.inputs import TelemetryReader
from yuntuo.fpga_link.telemetry import encode_frame


def test_fragmented_mirror_preserves_bytes_and_feedback(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(1)
        monkeypatch.setenv("YUNTUO_TELEMETRY_MIRROR_PORT", str(receiver.getsockname()[1]))
        reader = TelemetryReader("nv")
        packet = encode_frame({"timestamp_ms": 1000, "sequence": 9, "ax_raw": -123})
        try:
            for chunk in (packet[:23], packet[23:]):
                reader._ingest(chunk)
                received = receiver.recv(4096)
                magic, monotonic_ns, wall_ns = struct.unpack("<4sQQ", received[:20])
                assert magic == b"XIM1" and monotonic_ns > 0 and wall_ns > 0
                assert received[20:] == chunk
            samples = reader.drain()
            assert len(samples) == 1
            assert samples[0][0].raw["ax_raw"] == -123
            assert reader.latest()[0].sequence == 9
        finally:
            reader._mirror[0].close()


def test_failed_mirror_cannot_drop_control_sample(monkeypatch):
    monkeypatch.delenv("YUNTUO_TELEMETRY_MIRROR_PORT", raising=False)
    reader = TelemetryReader("nv")
    assert reader._mirror is None

    class FailedSocket:
        def sendto(self, *_):
            raise BlockingIOError("recorder unavailable")

    reader._mirror = (FailedSocket(), ("127.0.0.1", 19104))
    reader._ingest(encode_frame({"sequence": 10, "timestamp_ms": 1010}))
    assert reader.latest()[0].sequence == 10
    assert len(reader.drain()) == 1
