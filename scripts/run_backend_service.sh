#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Restore saved ALSA state first
alsactl restore >/dev/null 2>&1 || true

# Force ES8388 playback path - these must run AFTER alsactl restore
# because the saved state may have Output 1/2 at 0%
amixer -c 2 sset Speaker on >/dev/null 2>&1 || true
amixer -c 2 sset Headphone on >/dev/null 2>&1 || true
amixer -c 2 sset PCM 95% >/dev/null 2>&1 || true
amixer -c 2 sset 'Output 1' 90% >/dev/null 2>&1 || true
amixer -c 2 sset 'Output 2' 90% >/dev/null 2>&1 || true

# Capture mic volume
if [[ -n "${AUDIO_CAPTURE_CARD:-}" && -n "${AUDIO_CAPTURE_CONTROL:-}" && -n "${AUDIO_CAPTURE_VOLUME:-}" ]]; then
  amixer -c "${AUDIO_CAPTURE_CARD}" sset "${AUDIO_CAPTURE_CONTROL}" "${AUDIO_CAPTURE_VOLUME}" >/dev/null 2>&1 || true
fi

cd "${PROJECT_ROOT}/backend"
exec "${BACKEND_PYTHON}" -m uvicorn app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT}"
