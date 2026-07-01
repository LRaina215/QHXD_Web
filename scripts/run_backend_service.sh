#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Restore saved ALSA state (mic volumes etc)
alsactl restore >/dev/null 2>&1 || true

# Force ES8388 playback path — must run AFTER alsactl restore
# because saved state often has Output 1/2 at 0%
_set_output() {
  amixer -c 2 sset Speaker on >/dev/null 2>&1 || true
  amixer -c 2 sset Headphone on >/dev/null 2>&1 || true
  amixer -c 2 sset PCM 95% >/dev/null 2>&1 || true
  amixer -c 2 sset "Output 1" 90% >/dev/null 2>&1 || true
  amixer -c 2 sset "Output 2" 90% >/dev/null 2>&1 || true
}
_set_output

# Capture mic volume
if [[ -n "${AUDIO_CAPTURE_CARD:-}" && -n "${AUDIO_CAPTURE_CONTROL:-}" && -n "${AUDIO_CAPTURE_VOLUME:-}" ]]; then
  amixer -c "${AUDIO_CAPTURE_CARD}" sset "${AUDIO_CAPTURE_CONTROL}" "${AUDIO_CAPTURE_VOLUME}" >/dev/null 2>&1 || true
fi

# Background re-assert every 10s for the first 60s to fight any late reset
(
  for _ in 1 2 3 4 5 6; do
    sleep 10
    _set_output
  done
) &

cd "${PROJECT_ROOT}/backend"
exec "${BACKEND_PYTHON}" -m uvicorn app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT}"
