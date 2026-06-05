#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# 恢复上次保存的 ALSA mixer 设置（包括播放和录音音量）
alsactl restore >/dev/null 2>&1 || true

# 为 ES8388 板载声卡确保播放通路已打开
amixer -c 2 sset Speaker on >/dev/null 2>&1 || true
amixer -c 2 sset Headphone on >/dev/null 2>&1 || true
amixer -c 2 sset PCM 95% >/dev/null 2>&1 || true
amixer -c 2 sset "Output 1" 90% >/dev/null 2>&1 || true
amixer -c 2 sset "Output 2" 90% >/dev/null 2>&1 || true

# 恢复 USB 麦克风录音音量
if [[ -n "${AUDIO_CAPTURE_CARD:-}" && -n "${AUDIO_CAPTURE_CONTROL:-}" && -n "${AUDIO_CAPTURE_VOLUME:-}" ]]; then
  amixer -c "${AUDIO_CAPTURE_CARD}" sset "${AUDIO_CAPTURE_CONTROL}" "${AUDIO_CAPTURE_VOLUME}" >/dev/null 2>&1 || true
fi

cd "${PROJECT_ROOT}/backend"
exec "${BACKEND_PYTHON}" -m uvicorn app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT}"
