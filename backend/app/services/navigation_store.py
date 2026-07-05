import binascii
import struct
import threading
import zlib

from app.schemas import (
    NavigationMapMetadata,
    NavigationMapUpdateRequest,
    NavigationSnapshot,
)


class NavigationStore:
    """Thread-safe latest-value cache for the read-only navigation web bridge."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._latest: NavigationSnapshot | None = None
        self._map_metadata: NavigationMapMetadata | None = None
        self._map_png: bytes | None = None

    def update_snapshot(self, snapshot: NavigationSnapshot) -> NavigationSnapshot:
        with self._lock:
            self._latest = snapshot.model_copy(deep=True)
            return self._latest.model_copy(deep=True)

    def latest(self) -> NavigationSnapshot | None:
        with self._lock:
            return self._latest.model_copy(deep=True) if self._latest is not None else None

    def update_map(self, update: NavigationMapUpdateRequest) -> NavigationMapMetadata:
        expected_size = update.width * update.height
        if len(update.data) != expected_size:
            raise ValueError(f"occupancy data size {len(update.data)} != {expected_size}")

        png = self._encode_occupancy_png(update.width, update.height, update.data)
        metadata = NavigationMapMetadata(
            map_id=update.map_id,
            version=update.version,
            frame_id=update.frame_id,
            timestamp=update.timestamp,
            resolution=update.resolution,
            width=update.width,
            height=update.height,
            origin=update.origin,
        )
        with self._lock:
            self._map_png = png
            self._map_metadata = metadata
            return metadata.model_copy(deep=True)

    def map_metadata(self) -> NavigationMapMetadata | None:
        with self._lock:
            return self._map_metadata.model_copy(deep=True) if self._map_metadata is not None else None

    def map_png(self) -> tuple[NavigationMapMetadata, bytes] | None:
        with self._lock:
            if self._map_metadata is None or self._map_png is None:
                return None
            return self._map_metadata.model_copy(deep=True), bytes(self._map_png)

    @classmethod
    def _encode_occupancy_png(cls, width: int, height: int, data: list[int]) -> bytes:
        # OccupancyGrid starts at the map's lower-left; PNG starts at its upper-left.
        raw = bytearray()
        for source_y in range(height - 1, -1, -1):
            raw.append(0)  # PNG filter type: None
            row_start = source_y * width
            for value in data[row_start : row_start + width]:
                if value < 0:
                    raw.append(205)
                else:
                    clamped = min(100, max(0, value))
                    raw.append(round(254 * (100 - clamped) / 100))

        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        return signature + cls._png_chunk(b"IHDR", ihdr) + cls._png_chunk(
            b"IDAT", zlib.compress(bytes(raw), level=6)
        ) + cls._png_chunk(b"IEND", b"")

    @staticmethod
    def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
        body = chunk_type + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


navigation_store = NavigationStore()
