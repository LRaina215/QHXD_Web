#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
if [[ ! -f "${YOLO_CONFIG}" ]]; then
  echo "YOLO config not found: ${YOLO_CONFIG}" >&2
  exit 1
fi
cd "${PROJECT_ROOT}/experiments/rknn_yolo"
start_service yolo_camera "${YOLO_PYTHON}" camera_detect_service.py --config "${YOLO_CONFIG}"
echo "latest frame target: ${PROJECT_ROOT}/experiments/rknn_yolo/outputs/latest_camera_detection.jpg"
