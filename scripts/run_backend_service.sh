#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

if [[ -n "${AUDIO_CAPTURE_CARD:-}" && -n "${AUDIO_CAPTURE_CONTROL:-}" && -n "${AUDIO_CAPTURE_VOLUME:-}" ]]; then
  amixer -c "${AUDIO_CAPTURE_CARD}" sset "${AUDIO_CAPTURE_CONTROL}" "${AUDIO_CAPTURE_VOLUME}" >/dev/null 2>&1 || true
fi

cd "${PROJECT_ROOT}/backend"
exec "${BACKEND_PYTHON}" -m uvicorn app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT}"
