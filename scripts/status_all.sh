#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
status_service backend
status_service frontend
status_service yolo_camera
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
    echo "backend /health: OK"
  else
    echo "backend /health: unavailable"
  fi
fi
