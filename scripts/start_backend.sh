#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
if command -v curl >/dev/null 2>&1 && curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
  echo "backend already reachable: http://127.0.0.1:${BACKEND_PORT}/health"
  exit 0
fi
if [[ -n "${AUDIO_CAPTURE_CARD:-}" && -n "${AUDIO_CAPTURE_CONTROL:-}" && -n "${AUDIO_CAPTURE_VOLUME:-}" ]]; then
  amixer -c "${AUDIO_CAPTURE_CARD}" sset "${AUDIO_CAPTURE_CONTROL}" "${AUDIO_CAPTURE_VOLUME}" >/dev/null 2>&1 || true
fi
cd "${PROJECT_ROOT}/backend"
start_service backend "${BACKEND_PYTHON}" -m uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}"
if command -v curl >/dev/null 2>&1; then
  if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
    echo "backend health OK: http://127.0.0.1:${BACKEND_PORT}/health"
  else
    echo "backend process started but /health is not ready yet; check $(log_file backend)" >&2
  fi
fi
