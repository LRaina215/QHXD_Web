#!/usr/bin/env bash
# 云拓公网运行：后端（systemd 优先）+ fpga_bridge + 感知；公网网页由云端静态站 + 网关提供。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

unit_installed() {
  systemctl list-unit-files "$1" >/dev/null 2>&1
}

echo "starting YunTuo robot runtime..."

if unit_installed qhxd-backend.service; then
  echo "starting backend via systemd: qhxd-backend.service"
  sudo systemctl start qhxd-backend.service
else
  echo "qhxd-backend.service not installed; falling back to scripts/start_backend.sh"
  "${PROJECT_ROOT}/scripts/start_backend.sh"
fi

if command -v curl >/dev/null 2>&1; then
  curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null
  echo "backend health OK: http://127.0.0.1:${BACKEND_PORT}/health"
fi

for unit in yuntuo-fpga-bridge.service yuntuo-perception.service; do
  if unit_installed "${unit}"; then
    sudo systemctl start "${unit}"
    echo "started ${unit}"
  else
    echo "${unit} not installed; run scripts/install_yuntuo_services.sh"
  fi
done

if [[ "${PUBLIC_ROBOT_START_FRONTEND:-false}" == "true" ]]; then
  "${PROJECT_ROOT}/scripts/start_frontend.sh"
else
  echo "local frontend dev server skipped; public web is served by cloud static frontend."
fi

echo
"${PROJECT_ROOT}/scripts/status_public_robot.sh"
