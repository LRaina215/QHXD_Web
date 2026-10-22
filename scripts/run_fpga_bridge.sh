#!/usr/bin/env bash
# 云拓 fpga_bridge：RK3588 上唯一与 FPGA 导航通信的进程（替换 nav2_mission_executor，同样监听 127.0.0.1:9101）
set -euo pipefail

ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(--link "${YUNTUO_FPGA_LINK:-uart:/dev/yuntuo-fpga}")
[[ -n "${YUNTUO_CONTROL_TELEMETRY:-}" ]] && ARGS+=(--telemetry "$YUNTUO_CONTROL_TELEMETRY")
[[ -n "${YUNTUO_PRIOR_MAP:-}" ]] && ARGS+=(--map "$YUNTUO_PRIOR_MAP")
[[ "${YUNTUO_FPGA_IS_MOCK:-false}" =~ ^(1|true|yes|on)$ ]] && ARGS+=(--mock)

exec "${BACKEND_PYTHON:-python3}" -m yuntuo.fpga_bridge "${ARGS[@]}"
