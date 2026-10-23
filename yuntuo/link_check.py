"""FPGA 链路自检：python -m yuntuo.link_check（RK3588 上用 scripts/check_fpga_link.sh 运行）

依次检查并给出下一步建议：
  1. fpga_bridge 当前状态（链路类型、STATUS 新鲜度与频率、是否还在用模拟 FPGA）
  2. 板载 USB 串口（CH9102，/dev/yuntuo-fpga）：识别加载的镜像
       NAV0 = 导航镜像：FPGA 计时是否在走、发送报文频率、接收队列深度
       SFP1 = SFP 调试镜像：QPLL / RX 锁定、对齐、LOS、link_ready、收发计数
  3. 网口（SFP → 电口模块 → RK3588）：哪个网口有载波、是否配了 192.168.2.x、ARP、UDP 探测
       导航镜像回 STATUS → 测频率；调试镜像原样回显 → 测往返时延与丢包
  4. 底盘控制遥测串口（/dev/yuntuo-ctl）是否存在

只读原则：串口只发读寄存器命令；UDP 只发 found=0 的 TARGET（固件忽略）或回显负载。
fpga_bridge 正占用同一条链路时只看它的状态，不做原始探测（FPGA 按最近来包地址回发，探测会抢走 bridge 的数据）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link.links import (NAV_SYS_ID, REG_MBX_RX_STAT, REG_MBX_TX_SEQ, REG_SYS_ID, REG_SYS_TIME_US,
                                    RegisterBus)

SFP_SYS_ID = 0x53465031          # "SFP1"，导航仓库 integration/sfp 调试镜像
SFP_REGS = {"config": 0x04, "diagnostic": 0x10, "link_losses": 0x14, "rx_frames": 0x20, "rx_udp": 0x24,
            "rx_errors": 0x28, "arp_requests": 0x2C, "tx_frames": 0x30, "echoes": 0x34, "echo_drops": 0x38}
FPGA_MAC = "02:4e:56:00:00:02"
CH9102 = ("1a86", "55d4")


@dataclass
class Check:
    group: str
    name: str
    ok: bool | None              # True 通过 / False 失败 / None 未检查或仅提示
    detail: str
    hint: str | None = None


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def add(self, group: str, name: str, ok: bool | None, detail: str, hint: str | None = None) -> Check:
        check = Check(group, name, ok, detail, hint)
        self.checks.append(check)
        return check

    @property
    def failed(self) -> bool:
        return any(c.ok is False for c in self.checks)


# ---------------------------------------------------------------- 1. fpga_bridge


def check_bridge(report: Report, url: str) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url.rstrip("/") + "/health", timeout=2.0) as resp:
            snap = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        report.add("fpga_bridge", "运行状态", False, f"{url} 无响应：{exc}",
                   "sudo systemctl status yuntuo-fpga-bridge；journalctl -u yuntuo-fpga-bridge -n 50")
        return None
    platform = snap.get("platform") or {}
    link = str(snap.get("link") or "")
    mock = platform.get("nav_link") == "mock" or (platform.get("nav_link") == "offline" and "127.0.0.1" in link)
    report.facts["bridge_link"] = link
    report.facts["bridge_mock"] = mock
    age = snap.get("status_age_s")
    rate = platform.get("status_rate_hz")
    if not snap.get("link_open"):
        report.add("fpga_bridge", "导航链路", False, f"{link} 未打开：{snap.get('link_error')}",
                   "串口 / 网口不通时 bridge 会每隔几秒重试；先看下面串口、网口两节")
    elif age is None or age > 1.0:
        report.add("fpga_bridge", "导航链路", False, f"{link} 已打开，但 {age if age is not None else '从未'} s 没收到 STATUS",
                   "FPGA 没在发 STATUS：确认加载的是导航镜像（下面串口一节会识别 NAV0 / SFP1）")
    else:
        report.add("fpga_bridge", "导航链路", True,
                   f"{link}{'（模拟 FPGA）' if mock else ''}，STATUS {age:.1f} s 前，{rate} Hz，"
                   f"FPGA 状态 {platform.get('fpga_state')}，定位 {platform.get('loc_state')}")
    ctl = platform.get("control_link")
    report.add("fpga_bridge", "控制遥测", True if ctl in {"online", "mock"} else None,
               f"{ctl}，{platform.get('telemetry_rate_hz')} Hz" if ctl != "unknown" else "未配置（YUNTUO_CONTROL_TELEMETRY 为空）")
    if mock:
        report.add("fpga_bridge", "模式", None, "当前接的是模拟 FPGA（yuntuo-mock-fpga）",
                   "真 FPGA 通过后：改 .env 的 YUNTUO_FPGA_LINK / YUNTUO_FPGA_IS_MOCK / YUNTUO_CONTROL_TELEMETRY，"
                   "再不带 --mock-fpga 跑 scripts/install_yuntuo_services.sh")
    return snap


# ---------------------------------------------------------------- 2. 板载 USB 串口


def _usb_ids(dev: Path) -> tuple[str, str, str] | None:
    """tty 设备对应的 USB VID / PID / 序列号（sysfs 向上找）。"""
    node = Path("/sys/class/tty") / dev.name / "device"
    try:
        node = node.resolve()
    except OSError:
        return None
    for parent in [node, *node.parents]:
        vid, pid = parent / "idVendor", parent / "idProduct"
        if vid.exists() and pid.exists():
            serial = parent / "serial"
            return vid.read_text().strip(), pid.read_text().strip(), serial.read_text().strip() if serial.exists() else ""
    return None


def _holders(dev: Path) -> list[str]:
    """哪些进程打开了这个设备（扫描 /proc/*/fd，不需要 root 也能看到同用户进程）。"""
    found = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    target = str(dev.resolve())
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            for fd in (pid_dir / "fd").iterdir():
                if os.readlink(fd) == target:
                    cmd = (pid_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
                    found.append(f"{pid_dir.name} {cmd[:80]}")
                    break
        except OSError:
            continue
    return found


def probe_registers(bus: RegisterBus, sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic) -> dict:
    """读寄存器识别镜像并取关键状态；只发读命令。"""
    sys_id = bus.rd(REG_SYS_ID)
    out: dict[str, Any] = {"sys_id": f"0x{sys_id:08X}"}
    if sys_id == NAV_SYS_ID:
        out["image"] = "NAV0"
        t1, s1 = bus.rd(REG_SYS_TIME_US), bus.rd(REG_MBX_TX_SEQ)
        start = clock()
        sleep(1.0)
        t2, s2 = bus.rd(REG_SYS_TIME_US), bus.rd(REG_MBX_TX_SEQ)
        wall = max(clock() - start, 1e-3)
        out["fpga_clock_ratio"] = round(((t2 - t1) & 0xFFFFFFFF) / 1e6 / wall, 3)
        out["tx_msgs_per_s"] = round(((s2 - s1) & 0xFFFFFFFF) / wall, 1)
        out["rx_queue_depth"] = (bus.rd(REG_MBX_RX_STAT) >> 16) & 0xFF
    elif sys_id == SFP_SYS_ID:
        out["image"] = "SFP1"
        regs = {name: bus.rd(addr) for name, addr in SFP_REGS.items()}
        diag = regs["diagnostic"]
        out.update(regs)
        out["decoded"] = {"mode": "SGMII" if regs["config"] & 1 else "1000BASE-X", "autoneg": bool(regs["config"] & 2),
                          "qpll_locked": bool(diag & 1), "rx_locked": bool(diag & 2), "aligned": bool(diag & 4),
                          "los": bool(diag & 8), "link_ready": bool(diag & 16), "ip_reset": bool(diag & 32)}
    else:
        out["image"] = "unknown"
    return out


def check_serial(report: Report, device: str, *, raw: bool, port_factory: Callable[..., Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> dict | None:
    dev = Path(device)
    if not dev.exists():
        report.add("板载串口", "设备", None, f"{device} 不存在：FPGA 板的 USB 串口（CH9102 {CH9102[0]}:{CH9102[1]}）没接",
                   "接上 FPGA 板 USB 口后应自动出现；仍没有就看 lsusb 与 /etc/udev/rules.d/99-yuntuo.rules")
        return None
    real = dev.resolve()
    ids = _usb_ids(real)
    detail = f"{device} → {real}"
    if ids:
        detail += f"，USB {ids[0]}:{ids[1]}，序列号 {ids[2] or '无'}"
    ok_ids = ids is None or (ids[0], ids[1]) == CH9102
    report.add("板载串口", "设备", ok_ids, detail, None if ok_ids else "不是 CH9102：确认插的是 FPGA 板的调试 USB 口")
    if not os.access(real, os.R_OK | os.W_OK):
        report.add("板载串口", "权限", False, f"当前用户没有 {real} 的读写权限",
                   "sudo usermod -aG dialout $USER 后重新登录，或检查 udev 规则的 GROUP")
        return None
    holders = _holders(dev)
    if holders:
        report.add("板载串口", "占用", None, "；".join(holders),
                   "fpga_bridge 正在用这个串口：以上面 fpga_bridge 一节为准；要做原始探测先 sudo systemctl stop yuntuo-fpga-bridge")
        return None
    if not raw:
        report.add("板载串口", "寄存器", None, "--no-raw：未做原始探测")
        return None
    try:
        if port_factory is None:
            import serial  # pyserial

            port_factory = serial.Serial
        port = port_factory(str(real), 921600, timeout=0.5, write_timeout=0.5)
    except Exception as exc:  # noqa: BLE001
        report.add("板载串口", "打开", False, f"{real} 打不开：{exc}")
        return None
    try:
        if hasattr(port, "reset_input_buffer"):
            time.sleep(0.02)
            port.reset_input_buffer()
        info = probe_registers(RegisterBus(port), sleep=sleep, clock=clock)
    except Exception as exc:  # noqa: BLE001
        report.add("板载串口", "寄存器桥", False, f"921600 波特下读 SYS_ID 无应答：{exc}",
                   "FPGA 没有加载镜像（上电后要从 SRAM 下载），或加载的镜像不含 uart_bus_bridge")
        return None
    finally:
        try:
            port.close()
        except Exception:  # noqa: BLE001
            pass
    report.facts["serial"] = info
    if info["image"] == "NAV0":
        clock_ok = 0.95 <= info["fpga_clock_ratio"] <= 1.05
        report.add("板载串口", "镜像", True, f"导航镜像 NAV0（SYS_ID {info['sys_id']}）")
        report.add("板载串口", "FPGA 计时", clock_ok, f"SYS_TIME_US 走速 = 墙钟的 {info['fpga_clock_ratio']} 倍",
                   None if clock_ok else "计时停了或时钟不对：核对 PLL 与 SYS_TIME 时钟域")
        rate_ok = info["tx_msgs_per_s"] >= 4.0
        report.add("板载串口", "STATUS 发送", rate_ok, f"FPGA 每秒发出 {info['tx_msgs_per_s']} 条报文（应约 5 条 STATUS）",
                   None if rate_ok else "导航主循环没有在发 STATUS：看固件是否跑起来（RISC-V 程序已加载？）")
        report.add("板载串口", "接收队列", info["rx_queue_depth"] < 12, f"深度 {info['rx_queue_depth']} / 16")
    elif info["image"] == "SFP1":
        d = info["decoded"]
        report.add("板载串口", "镜像", True, f"SFP 调试镜像 SFP1（{d['mode']}，自协商 {'开' if d['autoneg'] else '关'}）")
        bits = "、".join(f"{k} {'✓' if d[k] else '✗'}" for k in ("qpll_locked", "rx_locked", "aligned", "link_ready"))
        hint = None
        if not d["qpll_locked"]:
            hint = "QPLL 没锁：125 MHz 参考时钟或 SerDes 配置问题"
        elif d["los"]:
            hint = "LOS：模块没插好或网线没接"
        elif not d["rx_locked"] or not d["aligned"]:
            hint = "收不到对端信号：换 BASE-X 强制 / SGMII 模式试（导航仓库 sfp_client.py status --mode ...）"
        elif not d["link_ready"]:
            hint = "物理层已锁定但链路没就绪：自协商没完成，试 --mode basex-forced"
        report.add("板载串口", "SFP 物理层", d["link_ready"], f"{bits}；LOS {'有' if d['los'] else '无'}；"
                   f"掉链 {info['link_losses']} 次", hint)
        report.add("板载串口", "SFP 计数", None, f"收帧 {info['rx_frames']}、UDP {info['rx_udp']}、错误 {info['rx_errors']}、"
                   f"ARP {info['arp_requests']}、回显 {info['echoes']}、丢弃 {info['echo_drops']}")
    else:
        report.add("板载串口", "镜像", False, f"未知镜像 SYS_ID {info['sys_id']}（导航 0x4E415630，SFP 调试 0x53465031）")
    return info


# ---------------------------------------------------------------- 3. 网口（SFP）


def wired_interfaces() -> list[dict]:
    """有线网卡：/sys/class/net 下有 device、不是无线、不是虚拟网卡。"""
    out = []
    base = Path("/sys/class/net")
    if not base.is_dir():
        return out
    for nic in sorted(base.iterdir()):
        if not (nic / "device").exists() or (nic / "wireless").exists() or (nic / "phy80211").exists():
            continue
        try:
            carrier = (nic / "carrier").read_text().strip() == "1"
        except OSError:
            carrier = False
        try:
            speed = int((nic / "speed").read_text().strip())
        except (OSError, ValueError):
            speed = None
        try:
            driver = os.path.basename(os.readlink(nic / "device" / "driver"))
        except OSError:
            driver = ""
        out.append({"name": nic.name, "carrier": carrier, "speed": speed if speed and speed > 0 else None,
                    "driver": driver, "addrs": _ipv4_addrs(nic.name)})
    return out


def _ipv4_addrs(ifname: str) -> list[str]:
    try:
        text = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", ifname], capture_output=True, text=True,
                              timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [part.split()[3] for part in text.splitlines() if len(part.split()) > 3]


def _same_subnet(cidr: str, ip: str) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_interface(cidr).network
    except ValueError:
        return False


def _neigh(ip: str) -> str:
    try:
        return subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def check_ethernet(report: Report, ip: str) -> dict | None:
    nics = wired_interfaces()
    report.facts["nics"] = nics
    if not nics:
        report.add("网口", "有线网卡", None, "没找到有线网卡（不在 RK3588 上运行？）")
        return None
    desc = "；".join(f"{n['name']}（{n['driver'] or '?'}）{'有载波 ' + str(n['speed']) + ' Mb/s' if n['carrier'] else '无载波'}"
                     f"{' ' + ','.join(n['addrs']) if n['addrs'] else ''}" for n in nics)
    up = [n for n in nics if n["carrier"]]
    in_subnet = [n for n in nics if any(_same_subnet(a, ip) for a in n["addrs"])]
    if not up:
        report.add("网口", "载波", None, desc, "网线没接或 SFP 链路没起来；接好后应看到某个网口“有载波 1000 Mb/s”")
        return None
    nic = (in_subnet or up)[0]
    speed_ok = nic["speed"] in (None, 1000)
    report.add("网口", "载波", speed_ok, desc,
               None if speed_ok else f"{nic['name']} 协商成 {nic['speed']} Mb/s，SFP 电口模块应为 1000：换网线或固定 1000 全双工")
    if not in_subnet:
        report.add("网口", "地址", False, f"没有网口配置在 {ip} 所在网段",
                   f"sudo nmcli con add type ethernet ifname {nic['name']} con-name yuntuo-sfp ipv4.method manual "
                   f"ipv4.addresses 192.168.2.10/24 ipv4.never-default yes ipv6.method disabled && sudo nmcli con up yuntuo-sfp")
        return None
    report.add("网口", "地址", True, f"{nic['name']} {','.join(nic['addrs'])}")
    return nic


def probe_udp(ip: str, port: int, *, echo_count: int = 50, listen_s: float = 2.0, timeout: float = 0.5) -> dict:
    """发一条 found=0 的 TARGET：导航镜像（固件忽略这条）会开始往这里推 STATUS；调试镜像原样回显。"""
    out: dict[str, Any] = {"endpoint": f"{ip}:{port}"}
    probe = nv.encode_target(0, 0, 0, found=False)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.connect((ip, port))
        sock.settimeout(timeout)
        first = None
        deadline = time.monotonic() + 1.5
        while first is None and time.monotonic() < deadline:
            sock.send(probe)
            try:
                first = sock.recv(2048)
            except (socket.timeout, ConnectionResetError, ConnectionRefusedError):
                continue
        if first is None:
            out["kind"] = "silent"
            return out
        if first == probe:
            out["kind"] = "echo"
            rtts, lost = [], 0
            for seq in range(echo_count):
                size = 64 if seq % 2 == 0 else 1472
                payload = struct.pack(">I", seq) + bytes((seq + i * 17) & 0xFF for i in range(size - 4))
                start = time.perf_counter()
                sock.send(payload)
                try:
                    while True:
                        answer = sock.recv(2048)
                        if answer == payload:
                            rtts.append((time.perf_counter() - start) * 1000)
                            break
                except (socket.timeout, ConnectionResetError):
                    lost += 1
            rtts.sort()
            out.update(sent=echo_count, lost=lost, rtt_ms_min=round(rtts[0], 2) if rtts else None,
                       rtt_ms_p50=round(rtts[len(rtts) // 2], 2) if rtts else None,
                       rtt_ms_max=round(rtts[-1], 2) if rtts else None)
            return out
        status = nv.decode(first)
        if not isinstance(status, nv.NavStatus):
            out.update(kind="other", first_bytes=first[:16].hex())
            return out
        out["kind"] = "nav"
        count, last, start = 1, status, time.monotonic()
        while time.monotonic() - start < listen_s:
            try:
                msg = nv.decode(sock.recv(2048))
            except (socket.timeout, ConnectionResetError):
                continue
            if isinstance(msg, nv.NavStatus):
                count, last = count + 1, msg
        out.update(status_hz=round(count / max(time.monotonic() - start, 1e-3), 1),
                   state=nv.STATE_NAMES.get(last.state, last.state), mode=nv.MODE_NAMES.get(last.mode, last.mode),
                   loc=nv.LOC_NAMES.get(last.loc_state, last.loc_state) if last.loc_state is not None else None)
        return out


def check_udp(report: Report, ip: str, port: int, *, raw: bool, echo_count: int) -> dict | None:
    link = str(report.facts.get("bridge_link") or "")
    if link.startswith(f"udp:{ip}"):
        report.add("网口", "UDP", None, f"fpga_bridge 正在用 {link}：以 fpga_bridge 一节为准，不做原始探测")
        return None
    if not raw:
        report.add("网口", "UDP", None, "--no-raw：未做原始探测")
        return None
    try:
        info = probe_udp(ip, port, echo_count=echo_count)
    except OSError as exc:
        report.add("网口", "UDP", False, f"发往 {ip}:{port} 失败：{exc}", "没有到 192.168.2.0/24 的路由：先配网口地址")
        return None
    report.facts["udp"] = info
    if info["kind"] == "echo":
        ok = info["lost"] == 0
        report.add("网口", "UDP 回显", ok, f"SFP 调试镜像回显 {info['sent'] - info['lost']}/{info['sent']}，"
                   f"往返 {info['rtt_ms_min']} / {info['rtt_ms_p50']} / {info['rtt_ms_max']} ms（最小 / 中位 / 最大，64 与 1472 B 交替）",
                   None if ok else "有丢包：看串口一节的 rx_errors / echo_drops，换网线再测")
    elif info["kind"] == "nav":
        ok = info["status_hz"] >= 4.0
        report.add("网口", "导航报文", ok, f"导航镜像经 SFP 推 STATUS {info['status_hz']} Hz，状态 {info['state']}，"
                   f"模式 {info['mode']}，定位 {info['loc']}",
                   "链路通了：.env 改 YUNTUO_FPGA_LINK=udp:192.168.2.100、YUNTUO_FPGA_IS_MOCK=false 后重装服务" if ok else None)
    elif info["kind"] == "other":
        report.add("网口", "UDP", False, f"{ip}:{port} 回了无法识别的数据：{info['first_bytes']}")
    else:
        neigh = _neigh(ip)
        arp_ok = FPGA_MAC in neigh.lower()
        report.add("网口", "UDP", False, f"{ip}:{port} 1.5 s 内无回应；ARP：{neigh or '无记录'}",
                   "ARP 已解析到 FPGA：镜像里没有 UDP 端点或端口不对" if arp_ok else
                   "ARP 也不通：链路没起来、对端 IP 不对，或 FPGA 镜像不含 SFP（当前整车工程尚未合入真实 SFP）")
    return info


# ---------------------------------------------------------------- 4. 控制遥测串口 + 汇总


def check_control_serial(report: Report, device: str) -> None:
    dev = Path(device)
    tele = os.getenv("YUNTUO_CONTROL_TELEMETRY", "")
    if dev.exists():
        report.add("控制遥测", "设备", True, f"{device} → {dev.resolve()}；.env YUNTUO_CONTROL_TELEMETRY={tele or '（空）'}",
                   None if tele.startswith("serial:") else f"接真控制板时设 YUNTUO_CONTROL_TELEMETRY=serial:{device}@230400")
    else:
        report.add("控制遥测", "设备", None, f"{device} 不存在（控制板遥测串口 CH340 1a86:7523 未接）"
                   + (f"；当前遥测来自 {tele}" if tele else ""))


def run(args: argparse.Namespace) -> Report:
    report = Report()
    report.facts["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    check_bridge(report, args.bridge)
    check_serial(report, args.device, raw=args.raw)
    if check_ethernet(report, args.ip) is not None or args.force_udp:
        check_udp(report, args.ip, args.port, raw=args.raw, echo_count=args.echo_count)
    check_control_serial(report, args.ctl_device)
    return report


MARK = {True: "✓", False: "✗", None: "–"}


def render(report: Report) -> str:
    lines = [f"云拓 FPGA 链路自检  {report.facts.get('time', '')}"]
    group = None
    for c in report.checks:
        if c.group != group:
            group = c.group
            lines.append(f"[{group}]")
        lines.append(f"  {MARK[c.ok]} {c.name}：{c.detail}")
        if c.hint and c.ok is not True:
            lines.append(f"      → {c.hint}")
    fails = [c for c in report.checks if c.ok is False]
    lines.append("结论：" + ("有 %d 项失败，按上面 → 的提示处理" % len(fails) if fails else "没有失败项（– 表示未接或未检查）"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="云拓 FPGA 链路自检（只读）")
    ap.add_argument("--bridge", default=os.getenv("YUNTUO_BRIDGE_URL", "http://127.0.0.1:9101"))
    ap.add_argument("--device", default="/dev/yuntuo-fpga")
    ap.add_argument("--ctl-device", default="/dev/yuntuo-ctl")
    ap.add_argument("--ip", default="192.168.2.100")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--echo-count", type=int, default=50)
    ap.add_argument("--no-raw", dest="raw", action="store_false", help="只看 fpga_bridge 与设备，不发探测")
    ap.add_argument("--force-udp", action="store_true", help="网口没检测到载波也做 UDP 探测（测试用）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = run(args)
    if args.json:
        print(json.dumps({"checks": [asdict(c) for c in report.checks], "facts": report.facts}, ensure_ascii=False,
                         indent=1, default=str))
    else:
        print(render(report))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
