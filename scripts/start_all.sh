#!/usr/bin/env bash
# 手动调试：后端 + 本机前端（PID 模式）。fpga_bridge / 感知由 systemd 管理，模拟链路用 start_yuntuo_sim.sh。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/start_backend.sh"
"${SCRIPT_DIR}/start_frontend.sh"
"${SCRIPT_DIR}/status_all.sh"
