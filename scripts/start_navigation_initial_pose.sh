#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

WORKSPACE="${LIVOX_WS:-/home/robomaster/livox_ws}"
PID_FILE="${RUNTIME_DIR}/navigation_initial_pose.pid"
LOG_FILE="${LOG_DIR}/navigation_initial_pose.log"

if [[ ! "${QHXD_NAV_INITIAL_POSE_ENABLED:-true}" =~ ^(1|true|yes|on)$ ]]; then
  echo "navigation initial pose is disabled"
  exit 0
fi

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "navigation initial pose watchdog is already running (pid ${existing_pid})"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if [[ ! -e "${WORKSPACE}/install/setup.bash" ]]; then
  echo "ERROR: missing livox workspace setup: ${WORKSPACE}/install/setup.bash" >&2
  exit 1
fi

POSE_X="${QHXD_NAV_INITIAL_POSE_X:--1.05}"
POSE_Y="${QHXD_NAV_INITIAL_POSE_Y:-4.54}"
POSE_YAW="${QHXD_NAV_INITIAL_POSE_YAW:-0.0}"
WAIT_SECONDS="${QHXD_NAV_INITIAL_POSE_WAIT_SECONDS:-600}"
RETRY_SECONDS="${QHXD_NAV_INITIAL_POSE_RETRY_SECONDS:-3}"

(
  set +e
  trap 'rm -f "${PID_FILE}"' EXIT
  exec >>"${LOG_FILE}" 2>&1
  echo "navigation initial pose watchdog started at $(date)"
  echo "configured pose: x=${POSE_X}, y=${POSE_Y}, yaw=${POSE_YAW}"

  set +u
  unset LD_LIBRARY_PATH
  source /opt/ros/humble/setup.bash
  source "${WORKSPACE}/install/setup.bash"

  read -r qz qw < <(python3 -c 'import math, sys; yaw=float(sys.argv[1]); print(math.sin(yaw / 2.0), math.cos(yaw / 2.0))' "${POSE_YAW}")
  deadline=$((SECONDS + WAIT_SECONDS))

  while (( SECONDS < deadline )); do
    if ! ROS2CLI_DISABLE_DAEMON=1 timeout 5 ros2 topic info /initialpose 2>/dev/null | grep -Eq 'Subscription count: [1-9][0-9]*'; then
      sleep "${RETRY_SECONDS}"
      continue
    fi

    message="{header: {frame_id: map}, pose: {pose: {position: {x: ${POSE_X}, y: ${POSE_Y}, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: ${qz}, w: ${qw}}}, covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0685]}}"
    if ROS2CLI_DISABLE_DAEMON=1 timeout 12 ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped "${message}"; then
      sleep 2
      if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/api/navigation/latest" 2>/dev/null | grep -Eq '"pose":\{"x":'; then
        echo "AMCL accepted the initial pose at $(date) (verified by navigation backend pose)"
        exit 0
      fi
      if ROS2CLI_DISABLE_DAEMON=1 timeout 8 ros2 topic echo /amcl_pose --once >/dev/null 2>&1; then
        echo "AMCL accepted the initial pose at $(date)"
        exit 0
      fi
      echo "initial pose was published, but /amcl_pose is not available yet; retrying"
    fi
    sleep "${RETRY_SECONDS}"
  done

  echo "navigation initial pose watchdog timed out after ${WAIT_SECONDS}s"
  exit 1
) &

echo $! >"${PID_FILE}"
echo "navigation initial pose watchdog started (pid $(cat "${PID_FILE}")); log: ${LOG_FILE}"
