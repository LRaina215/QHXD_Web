import math
import socket
import struct

import pytest

from yuntuo.fpga_link import links, nv_proto as nv, telemetry as tm
from yuntuo.fpga_link.nvmp import MapPackageError, build_test_package, parse_package


def test_goal_and_target_layout_matches_icd():
    goal = nv.encode_goal(9300, -2800)
    assert goal[:4] == b"NV\x01\x10" and len(goal) == 16
    assert struct.unpack("<iii", goal[4:]) == (9300, -2800, nv.YAW_DONT_CARE)
    tgt = nv.encode_target(1500, 200, 50, cls=39, conf_permille=912, latency_ms=45, track_id=7)
    assert tgt[:4] == b"NV\x01\x20" and len(tgt) == 24
    assert struct.unpack("<BBHiiiHH", tgt[4:]) == (1, 39, 912, 1500, 200, 50, 45, 7)
    assert nv.encode_mode("search") == b"NV\x01\x30\x03\x00\x00\x00"
    with pytest.raises(nv.ProtocolError):
        nv.encode_waypoints([(0, 0)] * 33)


def test_host_messages_roundtrip():
    wp = nv.decode_host(nv.encode_waypoints([(1, 2), (3, -4)], loop=True))
    assert wp.fields == {"points": [(1, 2), (3, -4)], "loop": True}
    pose = nv.decode_host(nv.encode_set_pose(-1000, -300, 9000, align=True, range_mm=800, range_cdeg=1500))
    assert pose.fields["align"] and pose.fields["range_mm"] == 800 and pose.fields["yaw_cdeg"] == 9000
    msgs = nv.map_messages(bytes(2500))
    assert [m[3] for m in msgs] == [0x40, 0x41, 0x41, 0x41, 0x42]
    assert len(msgs[3]) == 8 + 452


def test_status_decode_matches_nav_host_layout():
    # 与 nav 仓库 tools/nav_host.py parse() 相同的布局：<BBHiiiiihhHHI + loc_state + loc_quality
    raw = b"NV\x01\x80" + struct.pack("<BBHiiiiihhHHI", 1, 3, 9, 1200, -340, 4500, 3000, 100, 250, -120,
                                     nv.FLAG_TARGET_VALID | nv.FLAG_ODOM_OK, 0, 123456) + bytes((2, 87, 0, 0))
    s = nv.decode(raw)
    assert (s.mode_name, s.state_name, s.loc_name, s.loc_quality) == ("goto", "blocked", "ok", 87)
    assert s.target_valid and s.odom_ok and not s.lidar_ok
    assert math.isclose(s.yaw_rad, math.radians(45))
    assert nv.decode(nv.encode_status(s)) == s
    ack = nv.decode(nv.encode_map_ack(2048, 1))
    assert (ack.next_offset, ack.map_state_name) == (2048, "receiving")
    assert nv.decode(b"XX\x01\x80" + bytes(40)) is None


def test_angle_helpers():
    assert nv.rad_to_cdeg(math.pi / 2) == 9000
    assert nv.rad_to_cdeg(3 * math.pi / 2) == -9000
    assert nv.m_to_mm(-1.2345) == -1234 or nv.m_to_mm(-1.2345) == -1235


def test_crc16_ccitt_false_check_value():
    assert tm.crc16_ccitt_false(b"123456789") == 0x29B1


def test_control_v2_nv_envelope_preserves_every_original_field():
    # Distinct non-zero signed values make unit/offset/omitted-tail errors visible.
    values = {n: i+1 for i, n in enumerate(tm.NAMES_V1 + tm.NAMES_V2_EXTRA)}
    values.update(ax_raw=-32768, gz_raw=32767, gravity_z_q12=-4096,
                  left_delta=-123456, right_control_sequence=65535, timestamp_ms=0xFFFFFFFE)
    raw = tm.encode_frame(values)
    packet = b"NV\x01\x83" + raw
    decoded = nv.decode(packet)
    assert isinstance(decoded, tm.ControlFrame)
    assert decoded.version == 2 and decoded.raw == values
    for broken in (packet[:-1], packet+b"x", b"NV\x02\x83"+raw,
                   b"NV\x01\x83"+tm.encode_frame(values, version=1)):
        assert nv.decode(broken) is None
    corrupt = bytearray(packet)
    corrupt[100] ^= 1
    assert nv.decode(bytes(corrupt)) is None
    # A bad datagram cannot be completed from bytes of a later packet.
    assert nv.decode(packet[:40]) is None
    assert nv.decode(packet[40:]) is None
    assert nv.decode(packet).raw == values


def test_telemetry_decode_resync_and_units():
    frame = tm.encode_frame({"sequence": 5, "status": tm.ST_BMI_READY | tm.ST_ACTIVE, "gravity_z_q12": -4096,
                             "left_cms": 35, "right_cms": -12, "wz_q12": 2048, "sensor_error": 0})
    assert len(frame) == 126
    v1 = tm.encode_frame({"sequence": 7, "status": tm.ST_STOP_LATCHED, "sensor_error": 2}, version=1)
    assert len(v1) == 106
    bad = bytearray(frame)
    bad[20] ^= 0xFF
    dec = tm.TelemetryDecoder()
    out = dec.feed(b"\x00\xa5garbage" + bytes(bad) + frame[:50])
    out += dec.feed(frame[50:] + v1)
    assert [f.sequence for f in out] == [5, 7]
    assert dec.bad_crc == 1 and dec.skipped == 1
    f = out[0]
    assert f.active and f.calibrated and abs(f.roll_deg) < 1e-9 and abs(f.pitch_deg) < 1e-9
    assert (f.wheel_left_mps, f.wheel_right_mps, f.yaw_rate_radps) == (0.35, -0.12, 0.5)
    assert out[1].stop_latched and "bmi088_error:2" in out[1].faults() and out[1].roll_deg is None


class FakeBridgePort:
    """模拟 uart_bus_bridge：W/R 寄存器协议 + 邮箱注入 / 发送缓冲回读"""

    def __init__(self, *args, **kwargs):
        self.regs = {links.REG_SYS_ID: links.NAV_SYS_ID, links.REG_MBX_TX_SEQ: 0, links.REG_MBX_RX_STAT: 0}
        self.inj = []
        self.injected = []
        self.txb = b""
        self.out = bytearray()
        self.inbuf = bytearray()

    def fpga_send(self, msg):
        self.txb = msg + bytes(-len(msg) % 4)
        self.regs[links.REG_MBX_TX_LEN] = len(msg)
        self.regs[links.REG_MBX_TX_SEQ] += 1

    def write(self, data):
        self.inbuf += data
        while self.inbuf:
            if self.inbuf[:1] == b"W" and len(self.inbuf) >= 7:
                addr, val = struct.unpack(">HI", self.inbuf[1:7])
                del self.inbuf[:7]
                if addr == links.REG_MBX_INJ_DATA:
                    self.inj.append(val)
                elif addr == links.REG_MBX_INJ_GO:
                    n = self.regs[links.REG_MBX_INJ_LEN]
                    self.injected.append(b"".join(struct.pack("<I", w) for w in self.inj)[:n])
                    self.inj = []
                else:
                    self.regs[addr] = val
                self.out += b"K"
            elif self.inbuf[:1] == b"R" and len(self.inbuf) >= 3:
                (addr,) = struct.unpack(">H", self.inbuf[1:3])
                del self.inbuf[:3]
                if addr == links.REG_MBX_TXB_Q:
                    i = self.regs.get(links.REG_MBX_TXB_ADDR, 0)
                    val = struct.unpack_from("<I", self.txb, 4 * i)[0]
                else:
                    val = self.regs.get(addr, 0)
                self.out += b"D" + struct.pack(">I", val)
            else:
                break

    def read(self, n):
        data, self.out = bytes(self.out[:n]), self.out[n:]
        return data

    def close(self):
        pass


def test_board_uart_link_injects_and_reads_back():
    port = FakeBridgePort()
    link = links.BoardUartLink("COM_TEST", port_factory=lambda *a, **k: port)
    link.send(nv.encode_goal(1000, -500))
    assert port.injected == [nv.encode_goal(1000, -500)]
    assert link.recv(0.0) is None
    status = nv.encode_status(nv.NavStatus(0, 2, 1, 10, 20, 30, 40, 50, 0, 0, 8, 99, 2, 90))
    port.fpga_send(status)
    assert link.recv(0.1) == status
    assert link.recv(0.0) is None


def test_board_uart_link_rejects_wrong_device():
    port = FakeBridgePort()
    port.regs[links.REG_SYS_ID] = 0x12345678
    with pytest.raises(links.LinkError):
        links.BoardUartLink("COM_TEST", port_factory=lambda *a, **k: port)


def test_udp_link_loopback():
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(("127.0.0.1", 0))
    link = links.UdpLink("127.0.0.1", peer.getsockname()[1], local_port=0, bind_host="127.0.0.1")
    try:
        link.send(nv.encode_mode("idle"))
        data, addr = peer.recvfrom(64)
        assert data == nv.encode_mode("idle")
        peer.sendto(b"NV\x01\x82" + bytes(8), addr)
        assert link.recv(1.0)[:4] == b"NV\x01\x82"
    finally:
        link.close()
        peer.close()


def test_link_spec_parsing():
    assert links.parse_link_spec("uart:/dev/ttyACM0") == ("uart", {"device": "/dev/ttyACM0", "baud": 921600})
    assert links.parse_link_spec("udp:192.168.2.100") == ("udp", {"host": "192.168.2.100", "port": 9000})
    with pytest.raises(ValueError):
        links.parse_link_spec("tcp:1.2.3.4")


def test_nvmp_parse_and_occupancy():
    pkg = build_test_package(-5, -10, [[0, 100, 200], [254, 255, 0]], n_struct=2)
    m = parse_package(pkg)
    assert (m.width, m.height, m.origin_x_m, m.origin_y_m) == (3, 2, -0.5, -1.0)
    assert m.occupancy() == [0, 30, 60, 100, -1, 0]
    with pytest.raises(MapPackageError):
        parse_package(pkg[:-1] + b"\x07")
