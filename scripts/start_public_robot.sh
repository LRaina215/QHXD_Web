#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SERVICE_NAME="qhxd-backend.service"

service_installed() {
  systemctl list-unit-files "${SERVICE_NAME}" >/dev/null 2>&1
}

echo "starting public robot runtime..."

if service_installed; then
  echo "starting backend via systemd: ${SERVICE_NAME}"
  sudo systemctl start "${SERVICE_NAME}"
else
  echo "systemd backend service is not installed; falling back to scripts/start_backend.sh"
  "${PROJECT_ROOT}/scripts/start_backend.sh"
fi

if command -v curl >/dev/null 2>&1; then
  curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null
  echo "backend health OK: http://127.0.0.1:${BACKEND_PORT}/health"
fi

if [[ "${PUBLIC_ROBOT_START_FRONTEND:-false}" == "true" ]]; then
  "${PROJECT_ROOT}/scripts/start_frontend.sh"
else
  echo "local frontend dev server skipped; public web is served by cloud static frontend."
fi

if [[ "${PUBLIC_ROBOT_START_YOLO:-false}" == "true" ]]; then
  case "${PUBLIC_ROBOT_YOLO_MODE:-usb}" in
    hik)
      "${PROJECT_ROOT}/scripts/start_yolo_hik_camera.sh"
      ;;
    usb)
      "${PROJECT_ROOT}/scripts/start_yolo_camera.sh"
      ;;
    *)
      echo "unknown PUBLIC_ROBOT_YOLO_MODE=${PUBLIC_ROBOT_YOLO_MODE}; expected usb or hik" >&2
      exit 1
      ;;
  esac
else
  echo "YOLO camera service skipped; start USB/Hik camera service only when hardware is connected."
fi

if [[ "${PUBLIC_ROBOT_START_CBOARD:-false}" == "true" ]]; then
  "${PROJECT_ROOT}/scripts/start_cboard_comm.sh"
else
  echo "C board communication skipped; set PUBLIC_ROBOT_START_CBOARD=true when the C board is connected."
fi

echo
"${PROJECT_ROOT}/scripts/status_public_robot.sh"
