#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SERVICE_NAME="qhxd-backend.service"
SERVICE_SOURCE="${PROJECT_ROOT}/systemd/${SERVICE_NAME}"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -f "${SERVICE_SOURCE}" ]]; then
  echo "missing service file: ${SERVICE_SOURCE}" >&2
  exit 1
fi

chmod +x "${PROJECT_ROOT}/scripts/run_backend_service.sh"

if is_running "$(pid_file backend)"; then
  echo "stopping script-managed backend before enabling systemd service..."
  stop_service backend
fi

echo "installing ${SERVICE_NAME}..."
sudo install -m 0644 "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo
sudo systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo
if command -v curl >/dev/null 2>&1; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
      echo "backend health OK: http://127.0.0.1:${BACKEND_PORT}/health"
      exit 0
    fi
    sleep 1
  done
  echo "backend service started, but /health is not ready yet; check: sudo journalctl -u ${SERVICE_NAME} -n 80 --no-pager" >&2
  exit 1
fi
