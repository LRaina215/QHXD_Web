#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

PUBLIC_API_HEALTH_URL="${PUBLIC_API_HEALTH_URL:-https://api.lingxunrobot.cn/health}"
PUBLIC_WEB_URL="${PUBLIC_WEB_URL:-https://lingxunrobot.cn}"
PUBLIC_STATE_URL="${PUBLIC_STATE_URL:-https://lingxunrobot.cn/api/state/latest}"

echo "YunTuo robot status"
echo "project: ${PROJECT_ROOT}"
echo

for unit in qhxd-backend.service yuntuo-fpga-bridge.service yuntuo-perception.service; do
  if systemctl list-unit-files "${unit}" >/dev/null 2>&1; then
    echo "${unit}: $(systemctl is-active "${unit}" 2>/dev/null || true) / $(systemctl is-enabled "${unit}" 2>/dev/null || true)"
  else
    echo "${unit}: not installed"
  fi
done

if is_running "$(pid_file backend)"; then
  echo "PID debug backend: running pid=$(cat "$(pid_file backend)") log=$(log_file backend)"
fi
echo

check() {
  local label="$1" url="$2"
  shift 2
  if curl -fsS --max-time 8 "$@" "${url}" >/dev/null 2>&1; then
    echo "${label}: OK (${url})"
  else
    echo "${label}: unavailable (${url})"
  fi
}

if command -v curl >/dev/null 2>&1; then
  check "local backend /health" "http://127.0.0.1:${BACKEND_PORT}/health" --noproxy '*'
  check "fpga_bridge /health" "http://127.0.0.1:${NAV_MISSION_EXECUTOR_PORT:-9101}/health" --noproxy '*'
  bridge="$(curl --noproxy '*' -fsS --max-time 3 "http://127.0.0.1:${NAV_MISSION_EXECUTOR_PORT:-9101}/health" 2>/dev/null || true)"
  if [[ -n "${bridge}" ]]; then
    echo "fpga_bridge detail: ${bridge:0:240}"
  fi
  check "public gateway health" "${PUBLIC_API_HEALTH_URL}"
  check "public web" "${PUBLIC_WEB_URL}" -I
  check "public state proxy" "${PUBLIC_STATE_URL}"
fi

if command -v tailscale >/dev/null 2>&1; then
  echo
  echo "tailscale ip: $(tailscale ip -4 2>/dev/null | head -1 || true)"
fi

echo
status_service frontend
if [[ "${QHXD_VIDEO_STREAM_ENABLED:-false}" =~ ^(1|true|yes|on)$ ]]; then
  echo "H.264 cloud publisher: enabled"
else
  echo "H.264 cloud publisher: disabled"
fi
