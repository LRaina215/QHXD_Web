#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
status_service backend
status_service frontend
for unit in qhxd-backend yuntuo-fpga-bridge yuntuo-perception; do
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${unit}.service" >/dev/null 2>&1; then
    echo "${unit}.service: $(systemctl is-active "${unit}.service" 2>/dev/null || true)"
  fi
done
if command -v curl >/dev/null 2>&1; then
  for target in "backend|http://127.0.0.1:${BACKEND_PORT}/health" "fpga_bridge|http://127.0.0.1:${NAV_MISSION_EXECUTOR_PORT:-9101}/health"; do
    name="${target%%|*}"
    if curl --noproxy '*' -fsS "${target#*|}" >/dev/null 2>&1; then
      echo "${name} /health: OK"
    else
      echo "${name} /health: unavailable"
    fi
  done
fi
