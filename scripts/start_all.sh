#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/start_backend.sh"
"${SCRIPT_DIR}/start_frontend.sh"
"${SCRIPT_DIR}/start_yolo_camera.sh"
"${SCRIPT_DIR}/status_all.sh"
