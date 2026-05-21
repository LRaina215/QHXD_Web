#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HIK_YOLO_CONFIG="${HIK_YOLO_CONFIG:-${PROJECT_ROOT}/experiments/rknn_yolo/camera_config_hik.example.json}"
if [[ ! -f "${HIK_YOLO_CONFIG}" ]]; then
  echo "Hik YOLO config not found: ${HIK_YOLO_CONFIG}" >&2
  exit 1
fi
export YOLO_CONFIG="${HIK_YOLO_CONFIG}"
echo "starting YOLO camera service with Hik config: ${YOLO_CONFIG}"
"${SCRIPT_DIR}/start_yolo_camera.sh"
