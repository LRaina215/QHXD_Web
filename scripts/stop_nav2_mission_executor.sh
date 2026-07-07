#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
stop_service nav2_mission_executor

PORT="${NAV_MISSION_EXECUTOR_PORT:-9101}"
listener_pid="$(ss -ltnp 2>/dev/null | awk -v port=":${PORT}" '
  $0 ~ port {
    if (match($0, /pid=[0-9]+/)) {
      print substr($0, RSTART + 4, RLENGTH - 4)
      exit
    }
  }
')"
if [[ -n "${listener_pid}" ]]; then
  echo "stopping stale nav2_mission_executor listener on ${PORT}: pid=${listener_pid}"
  kill "${listener_pid}" 2>/dev/null || true
  for _ in 1 2 3; do
    kill -0 "${listener_pid}" 2>/dev/null || break
    sleep 1
  done
  kill -0 "${listener_pid}" 2>/dev/null && kill -9 "${listener_pid}" 2>/dev/null || true
fi
