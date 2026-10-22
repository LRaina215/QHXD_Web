#!/usr/bin/env bash
# FPGA 还没烧录时，用 mock_fpga 在本机扮演 FPGA 导航（UDP 127.0.0.1:9000）和底盘控制遥测（→ :9104）。
# 相机用真的 Astra（yuntuo-perception），所以这里不开虚拟相机。.env 里同时设置：
#   YUNTUO_FPGA_LINK=udp:127.0.0.1:9000  YUNTUO_FPGA_IS_MOCK=true  YUNTUO_CONTROL_TELEMETRY=udp:127.0.0.1:9104
set -euo pipefail

ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(--listen "${YUNTUO_MOCK_FPGA_LISTEN:-127.0.0.1:9000}" --telemetry-udp "${YUNTUO_MOCK_TELEMETRY_UDP:-127.0.0.1:9104}")
[[ "${YUNTUO_MOCK_FPGA_WITH_MAP:-false}" =~ ^(1|true|yes|on)$ ]] && ARGS+=(--with-map)

exec "${BACKEND_PYTHON:-python3}" -m yuntuo.mock_fpga "${ARGS[@]}"
