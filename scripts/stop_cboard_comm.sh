#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

if [[ "${CBOARD_WATCHDOG_INTERNAL_RESTART:-false}" != "true" ]]; then
  stop_service cboard_watchdog
fi

stop_matching_processes() {
  local pattern="$1"
  local label="$2"
  local pids
  pids="$(pgrep -f "${pattern}" 2>/dev/null || true)"
  [[ -n "${pids}" ]] || return 0

  echo "stopping leftover ${label}: ${pids//$'\n'/ }"
  local pid
  for pid in ${pids}; do
    [[ "${pid}" == "$$" ]] && continue
    kill "${pid}" 2>/dev/null || true
  done

  for _ in 1 2 3 4 5; do
    pids="$(pgrep -f "${pattern}" 2>/dev/null || true)"
    [[ -z "${pids}" ]] && return 0
    sleep 1
  done

  echo "leftover ${label} still running; sending SIGKILL"
  for pid in ${pids}; do
    [[ "${pid}" == "$$" ]] && continue
    kill -9 "${pid}" 2>/dev/null || true
  done
}

live_standard_robot_pids() {
  local pid stat
  for pid in $(pgrep -x "standard_robot_" 2>/dev/null || true); do
    stat="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
    [[ -n "${stat}" && "${stat}" != Z* ]] && echo "${pid}"
  done
}

stop_service ros2_imu_bridge
stop_service standard_robot_pp_ros2

stop_matching_processes "ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py" "standard_robot_pp_ros2 launch"
node_pids="$(live_standard_robot_pids)"
if [[ -n "${node_pids}" ]]; then
  echo "stopping leftover standard_robot_pp_ros2 node: ${node_pids//$'\n'/ }"
  for pid in ${node_pids}; do
    kill "${pid}" 2>/dev/null || true
  done
  for _ in 1 2 3 4 5; do
    node_pids="$(live_standard_robot_pids)"
    [[ -z "${node_pids}" ]] && break
    sleep 1
  done
  if [[ -n "${node_pids}" ]]; then
    echo "leftover standard_robot_pp_ros2 node still running; sending SIGKILL"
    for pid in ${node_pids}; do
      kill -9 "${pid}" 2>/dev/null || true
    done
  fi
fi

if [[ -n "$(live_standard_robot_pids)" ]]; then
  echo "warning: standard_robot_pp_ros2_node is still running outside script pid management:" >&2
  ps -eo pid,ppid,cmd | grep -F "standard_robot_pp_ros2_node" | grep -v grep >&2 || true
fi
