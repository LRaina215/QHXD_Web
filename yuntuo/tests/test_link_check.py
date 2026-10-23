"""链路自检：寄存器桥识别 NAV0 / SFP1 镜像、UDP 探测区分导航镜像与回显镜像、bridge 占用链路时不做原始探测。"""
import socket
import struct
import threading
import time

from yuntuo import link_check as lc
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link.links import NAV_SYS_ID, REG_MBX_RX_STAT, REG_MBX_TX_SEQ, REG_SYS_ID, REG_SYS_TIME_US, RegisterBus
from yuntuo.mock_fpga import MockFpgaCore


class FakeBridgePort:
    """uart_bus_bridge：'R'+u16 -> 'D'+u32；'W'+u16+u32 -> 'K'（大端）。寄存器值可以是可调用对象。"""

    def __init__(self, regs):
        self.regs, self.out = regs, b""

    def write(self, data):
        if data[:1] == b"R":
            (addr,) = struct.unpack(">H", data[1:3])
            value = self.regs.get(addr, 0)
            self.out += b"D" + struct.pack(">I", (value() if callable(value) else value) & 0xFFFFFFFF)
        elif data[:1] == b"W":
            self.out += b"K"

    def read(self, n):
        chunk, self.out = self.out[:n], self.out[n:]
        return chunk


def test_register_probe_identifies_nav_image_and_measures_status_rate():
    clock = {"t": 0.0}
    regs = {REG_SYS_ID: NAV_SYS_ID,
            REG_SYS_TIME_US: lambda: int(clock["t"] * 1e6),
            REG_MBX_TX_SEQ: lambda: int(clock["t"] * 5),
            REG_MBX_RX_STAT: 2 << 16}
    info = lc.probe_registers(RegisterBus(FakeBridgePort(regs)),
                              sleep=lambda s: clock.__setitem__("t", clock["t"] + s), clock=lambda: clock["t"])
    assert info["image"] == "NAV0"
    assert info["fpga_clock_ratio"] == 1.0 and info["tx_msgs_per_s"] == 5.0 and info["rx_queue_depth"] == 2


def test_register_probe_decodes_sfp_debug_image():
    regs = {REG_SYS_ID: lc.SFP_SYS_ID, 0x04: 0b010, 0x10: 0b10111, 0x24: 12, 0x34: 12}
    info = lc.probe_registers(RegisterBus(FakeBridgePort(regs)), sleep=lambda s: None)
    assert info["image"] == "SFP1"
    d = info["decoded"]
    assert (d["mode"], d["autoneg"], d["qpll_locked"], d["aligned"], d["los"], d["link_ready"]) == \
        ("1000BASE-X", True, True, True, False, True)


def _serve(handler):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.05)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                data, src = sock.recvfrom(2048)
            except (socket.timeout, ConnectionResetError):
                handler(None, None, sock)
                continue
            handler(data, src, sock)
        sock.close()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return sock.getsockname()[1], lambda: (stop.set(), thread.join(1.0))


def test_udp_probe_against_echo_image_measures_rtt():
    port, stop = _serve(lambda data, src, sock: data is not None and sock.sendto(data, src))
    try:
        info = lc.probe_udp("127.0.0.1", port, echo_count=10)
    finally:
        stop()
    assert info["kind"] == "echo" and info["sent"] == 10 and info["lost"] == 0 and info["rtt_ms_p50"] is not None


def test_udp_probe_against_nav_image_counts_status():
    core = MockFpgaCore(with_map=True)
    state = {"peer": None, "next": 0.0}

    def handler(data, src, sock):
        now = time.monotonic()
        if data is not None:
            for reply in core.handle(data, now) or []:
                sock.sendto(reply, src)
            state["peer"] = src
        if state["peer"] and now >= state["next"]:
            state["next"] = now + 0.2
            core.step(0.2, now)
            sock.sendto(nv.encode_status(core.status(now)), state["peer"])

    port, stop = _serve(handler)
    try:
        info = lc.probe_udp("127.0.0.1", port, listen_s=1.0)
    finally:
        stop()
    assert info["kind"] == "nav" and 3.5 <= info["status_hz"] <= 7.0 and info["loc"] == "ok"


def test_no_raw_probe_while_bridge_owns_the_udp_link():
    report = lc.Report(facts={"bridge_link": "udp:192.168.2.100"})
    assert lc.check_udp(report, "192.168.2.100", 9000, raw=True, echo_count=1) is None
    assert report.checks[-1].ok is None and "fpga_bridge 正在用" in report.checks[-1].detail
