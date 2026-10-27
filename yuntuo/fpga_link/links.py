"""RK3588 <-> FPGA 导航报文链路。

  udp:IP[:端口]            SFP 网口（FPGA 默认 192.168.2.100:9000，本机 9001）。1G Serial Ethernet IP 未生成前不可用。
  uart:/dev/ttyACM0[@波特率] 板载 USB 串口（uart_bus_bridge，921600 8N1，方案 R0，2026-10-01 上板通过）：
                           报文写入 MBX.INJ_* 注入接收队列；FPGA 发出的报文留在发送缓冲，经 MBX.TX_SEQ /
                           MBX.TXB_ADDR / MBX.TXB_Q 回读（只保留最新一条，轮询慢于 5 Hz 会丢 STATUS，属正常）。

链路对象只允许一个线程使用（fpga_bridge 的 I/O 线程独占），不做内部加锁。
"""
from __future__ import annotations

import socket
import struct
import time
from typing import Any, Callable, Protocol

# 导航寄存器地址（导航仓库 docs/2_interface/regmap.md、model/nav_regs_map.py）
REG_SYS_ID = 0x0000
REG_SYS_TIME_US = 0x0008
REG_MBX_RX_STAT = 0x1200
REG_MBX_TX_LEN = 0x1224
REG_MBX_INJ_DATA = 0x1230
REG_MBX_INJ_LEN = 0x1234
REG_MBX_INJ_GO = 0x1238
REG_MBX_TXB_ADDR = 0x123C
REG_MBX_TXB_Q = 0x1240
REG_MBX_TX_SEQ = 0x1244
NAV_SYS_ID = 0x4E415630          # "NAV0"
RX_QUEUE_HIGH_WATER = 12         # 接收描述符队列 16 项，留余量


class LinkError(IOError):
    pass


class NavLink(Protocol):
    kind: str
    reliable: bool               # Transport property only; application MAP_ACK is still required.

    def send(self, msg: bytes) -> None: ...

    def recv(self, timeout: float = 0.2) -> bytes | None: ...

    def close(self) -> None: ...


class UdpLink:
    kind = "udp"
    reliable = False

    def __init__(self, host: str = "192.168.2.100", port: int = 9000, local_port: int = 9001,
                 bind_host: str = "0.0.0.0") -> None:
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind_host, local_port))
        self.sock.settimeout(0.2)

    def send(self, msg: bytes) -> None:
        self.sock.sendto(msg, self.addr)

    def recv(self, timeout: float = 0.2) -> bytes | None:
        self.sock.settimeout(max(0.001, timeout))
        try:
            data, _ = self.sock.recvfrom(2048)
            return data
        except (socket.timeout, BlockingIOError):
            return None
        except ConnectionResetError:
            # Windows 上对端端口未监听时会收到 ICMP 复位，忽略
            return None

    def close(self) -> None:
        self.sock.close()


class RegisterBus:
    """uart_bus_bridge 的寄存器读写：'W' + u16 地址 + u32 值（大端）-> 'K'；'R' + u16 地址 -> 'D' + u32。"""

    def __init__(self, port: Any) -> None:
        self.port = port

    def wr(self, addr: int, value: int) -> None:
        self.port.write(b"W" + struct.pack(">HI", addr, value & 0xFFFFFFFF))
        if self.port.read(1) != b"K":
            raise LinkError(f"写 0x{addr:04X} 无应答")

    def wr_burst(self, items: list[tuple[int, int]], depth: int = 64) -> None:
        """连续写，最多 depth 条在途再统一收应答（串口往返远大于命令本身）"""
        pending = 0
        for addr, value in items:
            self.port.write(b"W" + struct.pack(">HI", addr, value & 0xFFFFFFFF))
            pending += 1
            if pending >= depth:
                self._expect_acks(pending)
                pending = 0
        if pending:
            self._expect_acks(pending)

    def _expect_acks(self, n: int) -> None:
        if self.port.read(n) != b"K" * n:
            raise LinkError("连续写应答缺失")

    def rd(self, addr: int) -> int:
        self.port.write(b"R" + struct.pack(">H", addr))
        r = self.port.read(5)
        if len(r) != 5 or r[:1] != b"D":
            raise LinkError(f"读 0x{addr:04X} 无应答")
        return struct.unpack(">I", r[1:])[0]


class BoardUartLink:
    """板载 USB 串口 + 邮箱注入（方案 R0）。port_factory 便于测试时注入假串口。"""

    kind = "uart"
    reliable = True

    def __init__(self, device: str, baud: int = 921600, *, port_factory: Callable[..., Any] | None = None,
                 check_id: bool = True) -> None:
        if port_factory is None:
            import serial  # pyserial

            port_factory = serial.Serial
        self.device = device
        self.port = port_factory(device, baud, timeout=0.3, write_timeout=0.5)
        if hasattr(self.port, "reset_input_buffer"):
            self.port.reset_input_buffer()
        self.bus = RegisterBus(self.port)
        if check_id:
            sys_id = self.bus.rd(REG_SYS_ID)
            if sys_id != NAV_SYS_ID:
                self.close()
                raise LinkError(f"{device} 上不是导航子系统（SYS_ID=0x{sys_id:08X}，期望 0x{NAV_SYS_ID:08X}）")
        self.last_seq = self.bus.rd(REG_MBX_TX_SEQ)

    def send(self, msg: bytes) -> None:
        for _ in range(200):
            if ((self.bus.rd(REG_MBX_RX_STAT) >> 16) & 0xFF) < RX_QUEUE_HIGH_WATER:
                break
            time.sleep(0.005)
        else:
            raise LinkError("FPGA 接收队列持续满，报文未注入")
        padded = msg + bytes((-len(msg)) % 4)
        words = [struct.unpack_from("<I", padded, i)[0] for i in range(0, len(padded), 4)]
        self.bus.wr_burst([(REG_MBX_INJ_DATA, w) for w in words] +
                          [(REG_MBX_INJ_LEN, len(msg)), (REG_MBX_INJ_GO, 1)])

    def recv(self, timeout: float = 0.2) -> bytes | None:
        deadline = time.monotonic() + timeout
        while True:
            seq = self.bus.rd(REG_MBX_TX_SEQ)
            if seq != self.last_seq:
                n = self.bus.rd(REG_MBX_TX_LEN) & 0xFFFF
                if n == 0 or n > 2048:
                    self.last_seq = seq
                else:
                    words = []
                    for i in range((n + 3) // 4):
                        self.bus.wr(REG_MBX_TXB_ADDR, i)
                        words.append(self.bus.rd(REG_MBX_TXB_Q))
                    if self.bus.rd(REG_MBX_TX_SEQ) == seq:      # 读取期间没有被新报文覆盖
                        self.last_seq = seq
                        return b"".join(struct.pack("<I", w) for w in words)[:n]
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    def close(self) -> None:
        try:
            self.port.close()
        except Exception:
            pass


def parse_link_spec(spec: str) -> tuple[str, dict[str, Any]]:
    kind, _, rest = spec.partition(":")
    kind = kind.strip().lower()
    if kind == "udp":
        host, _, port = rest.partition(":")
        return "udp", {"host": host or "192.168.2.100", "port": int(port) if port else 9000}
    if kind == "uart":
        device, _, baud = rest.partition("@")
        if not device:
            raise ValueError("uart 链路需要设备名，例如 uart:/dev/ttyACM0")
        return "uart", {"device": device, "baud": int(baud) if baud else 921600}
    raise ValueError(f"未知链路 {spec}（支持 udp:IP[:端口]、uart:设备[@波特率]）")


def open_link(spec: str, *, local_port: int = 9001) -> NavLink:
    kind, args = parse_link_spec(spec)
    if kind == "udp":
        return UdpLink(args["host"], args["port"], local_port=local_port)
    return BoardUartLink(args["device"], args["baud"])
