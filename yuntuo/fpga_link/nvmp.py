"""先验地图包 .nvmp（导航仓库 model/prior_map.py 生成）的只读解析：校验 + 取出全局代价图给网页显示。

包格式（小端）：头 40 B：'NVMP' | u16 版本 | u16 标志 | i32 ox, oy | u32 n_struct | i32 gox, goy | u16 gnx, gny
              | u32 body_crc32 | u32 body_len；体：n_struct × 5 B 结构槽 + gnx×gny 字节代价
              （行优先，0..200 可通行代价，254 致命，255 未知）。代价图一格 = 2 个全局 5 cm 格 = 10 cm。
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

HDR = struct.Struct("<4sHHiiIiiHHII")
MAGIC = b"NVMP"
SUPPORTED_VERSIONS = (2,)
COST_CELL_M = 0.10
COST_LETHAL = 254
COST_UNKNOWN = 255
COST_FREE_MAX = 200


class MapPackageError(ValueError):
    pass


@dataclass(frozen=True)
class PriorMap:
    version: int
    n_struct: int
    origin_x_m: float
    origin_y_m: float
    width: int
    height: int
    cost: bytes
    digest: str
    size: int

    def occupancy(self) -> list[int]:
        """ROS OccupancyGrid 语义：-1 未知，0..100 占用率（致命 = 100，可通行代价线性映射到 0..60）"""
        out = []
        for c in self.cost:
            if c == COST_UNKNOWN:
                out.append(-1)
            elif c >= COST_LETHAL:
                out.append(100)
            else:
                out.append(int(round(min(c, COST_FREE_MAX) * 60 / COST_FREE_MAX)))
        return out


def parse_package(data: bytes) -> PriorMap:
    if len(data) < HDR.size:
        raise MapPackageError("地图包长度不足 40 字节")
    magic, ver, _flags, _ox, _oy, n, gox, goy, gnx, gny, crc, blen = HDR.unpack_from(data)
    if magic != MAGIC:
        raise MapPackageError("不是 .nvmp 地图包（魔数不符）")
    if ver not in SUPPORTED_VERSIONS:
        raise MapPackageError(f"地图包版本 {ver}，固件只接受版本 {SUPPORTED_VERSIONS}（用 tools/map_tool.py 重新生成）")
    body = data[HDR.size:HDR.size + blen]
    if len(body) != blen or zlib.crc32(body) != crc:
        raise MapPackageError("地图包损坏（长度或 CRC 不符）")
    cost = body[5 * n:]
    if len(cost) != gnx * gny:
        raise MapPackageError(f"代价图大小 {len(cost)} 与 {gnx}×{gny} 不符")
    return PriorMap(
        version=ver,
        n_struct=n,
        origin_x_m=gox * COST_CELL_M,
        origin_y_m=goy * COST_CELL_M,
        width=gnx,
        height=gny,
        cost=bytes(cost),
        digest=hashlib.sha1(data).hexdigest()[:12],
        size=len(data),
    )


def build_test_package(gox: int, goy: int, cost_rows: list[list[int]], n_struct: int = 0) -> bytes:
    """测试 / 模拟器用：构造一个合法的包（结构槽填 0）"""
    gny = len(cost_rows)
    gnx = len(cost_rows[0]) if gny else 0
    body = bytes(5 * n_struct) + bytes(v for row in cost_rows for v in row)
    return HDR.pack(MAGIC, 2, 0, 0, 0, n_struct, gox, goy, gnx, gny, zlib.crc32(body), len(body)) + body
