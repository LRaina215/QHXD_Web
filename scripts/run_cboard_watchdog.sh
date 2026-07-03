#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

CBOARD_DEVICE="${CBOARD_DEVICE:-/dev/ttyCBoard}"
HEARTBEAT_FILE="${ROS2_IMU_HEARTBEAT_FILE:-${RUNTIME_DIR}/ros2_imu_bridge.heartbeat}"
CHECK_INTERVAL="${CBOARD_WATCHDOG_CHECK_INTERVAL:-5}"
STALE_SECONDS="${CBOARD_WATCHDOG_STALE_SECONDS:-15}"
RESTART_COOLDOWN="${CBOARD_WATCHDOG_RESTART_COOLDOWN:-30}"
started_at="$(date +%s)"
last_restart_at=0

echo "C board watchdog started: device=${CBOARD_DEVICE}, stale=${STALE_SECONDS}s"

while true; do
  sleep "${CHECK_INTERVAL}"
  [[ -e "${CBOARD_DEVICE}" ]] || continue

  now="$(date +%s)"
  if [[ -e "${HEARTBEAT_FILE}" ]]; then
    heartbeat_at="$(stat -c %Y "${HEARTBEAT_FILE}" 2>/dev/null || echo 0)"
  else
    heartbeat_at="${started_at}"
  fi
  age=$((now - heartbeat_at))
  (( age > STALE_SECONDS )) || continue
  (( now - last_restart_at > RESTART_COOLDOWN )) || continue

  echo "IMU heartbeat stale for ${age}s; restarting C board communication."
  last_restart_at="${now}"
  rm -f "${HEARTBEAT_FILE}"
  CBOARD_WATCHDOG_INTERNAL_RESTART=true "${SCRIPT_DIR}/stop_cboard_comm.sh" || true
  CBOARD_WATCHDOG_INTERNAL_RESTART=true "${SCRIPT_DIR}/start_cboard_comm.sh" || true
  started_at="$(date +%s)"
done
