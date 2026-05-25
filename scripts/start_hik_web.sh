#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

HIK_YOLO_CONFIG="${HIK_YOLO_CONFIG:-${PROJECT_ROOT}/experiments/rknn_yolo/camera_config_hik.example.json}"
HIK_WEB_RESTART_YOLO="${HIK_WEB_RESTART_YOLO:-true}"
HIK_WEB_RESTART_FRONTEND="${HIK_WEB_RESTART_FRONTEND:-true}"

if [[ ! -f "${HIK_YOLO_CONFIG}" ]]; then
  echo "Hik YOLO config not found: ${HIK_YOLO_CONFIG}" >&2
  exit 1
fi

echo "starting QHXD Hik web stack"
echo "backend port: ${BACKEND_PORT}"
echo "frontend port: ${FRONTEND_PORT}"
echo "hik yolo config: ${HIK_YOLO_CONFIG}"

"${SCRIPT_DIR}/start_backend.sh"

case "${HIK_WEB_RESTART_FRONTEND}" in
  1|true|TRUE|yes|YES|on|ON)
    stop_service frontend
    for pid in $(pgrep -f "${PROJECT_ROOT}/frontend/node_modules/.bin/vite --host 0.0.0.0 --port ${FRONTEND_PORT}" || true); do
      echo "stopping unmanaged frontend vite: pid=${pid}"
      kill "${pid}" 2>/dev/null || true
    done
    ;;
esac

"${SCRIPT_DIR}/start_frontend.sh"

case "${HIK_WEB_RESTART_YOLO}" in
  1|true|TRUE|yes|YES|on|ON)
    stop_service yolo_camera
    ;;
esac

HIK_YOLO_CONFIG="${HIK_YOLO_CONFIG}" "${SCRIPT_DIR}/start_yolo_hik_camera.sh"
"${SCRIPT_DIR}/status_all.sh"
