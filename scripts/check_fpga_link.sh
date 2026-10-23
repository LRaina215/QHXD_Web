#!/usr/bin/env bash
# FPGA 链路自检（只读）：fpga_bridge 状态、板载 USB 串口镜像识别（NAV0 / SFP1）、SFP 网口载波 / 地址 / UDP 探测、控制遥测串口。
#   ./scripts/check_fpga_link.sh              文字报告；有失败项时退出码 1
#   ./scripts/check_fpga_link.sh --json       机器可读
#   ./scripts/check_fpga_link.sh --no-raw     只看状态，不向串口 / 网口发探测
# fpga_bridge 占用串口或 UDP 链路时，脚本只看它的状态；要做原始探测先 sudo systemctl stop yuntuo-fpga-bridge。
set -euo pipefail

ROOT="${QHXD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

exec "${BACKEND_PYTHON:-python3}" -m yuntuo.link_check "$@"
