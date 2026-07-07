#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
PORT="${NAV_MISSION_EXECUTOR_PORT:-9101}"

listener_pid="$(ss -ltnp 2>/dev/null | awk -v port=":${PORT}" '
  $0 ~ port {
    if (match($0, /pid=[0-9]+/)) {
      print substr($0, RSTART + 4, RLENGTH - 4)
      exit
    }
  }
')"
managed_pid="$(cat "$(pid_file nav2_mission_executor)" 2>/dev/null || true)"
if [[ -n "${listener_pid}" && "${listener_pid}" != "${managed_pid}" ]]; then
  echo "stopping stale nav2_mission_executor listener on ${PORT}: pid=${listener_pid}"
  kill "${listener_pid}" 2>/dev/null || true
  for _ in 1 2 3; do
    kill -0 "${listener_pid}" 2>/dev/null || break
    sleep 1
  done
  kill -0 "${listener_pid}" 2>/dev/null && kill -9 "${listener_pid}" 2>/dev/null || true
  rm -f "$(pid_file nav2_mission_executor)"
fi

start_service nav2_mission_executor "$SCRIPT_DIR/run_nav2_mission_executor.sh"
for _ in 1 2 3 4 5; do
  if curl --noproxy '*' -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Nav2 mission executor health OK"
    exit 0
  fi
  sleep 1
done
echo "Nav2 mission executor process started but health endpoint is unavailable" >&2
exit 1
