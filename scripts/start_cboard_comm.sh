#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
QHXD_SETUP="${QHXD_SETUP:-${PROJECT_ROOT}/install/setup.bash}"
CBOARD_DEVICE="${CBOARD_DEVICE:-/dev/ttyCBoard}"
CBOARD_PARAMS_FILE="${CBOARD_PARAMS_FILE:-${PROJECT_ROOT}/standard_robot_pp_ros2/config/standard_robot_pp_ros2_pointlio.yaml}"
CBOARD_USE_RESPAWN="${CBOARD_USE_RESPAWN:-false}"
ROS2_IMU_TOPIC="${ROS2_IMU_TOPIC:-/serial/imu_backend}"
ROS2_IMU_BRIDGE_RATE_HZ="${ROS2_IMU_BRIDGE_RATE_HZ:-20}"
ROS2_IMU_BRIDGE_SOURCE="${ROS2_IMU_BRIDGE_SOURCE:-rk3588_cboard_ros2}"
ROS2_IMU_BRIDGE_BACKEND_URL="${ROS2_IMU_BRIDGE_BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"
ROS2_IMU_HEARTBEAT_FILE="${ROS2_IMU_HEARTBEAT_FILE:-${RUNTIME_DIR}/ros2_imu_bridge.heartbeat}"
ROS2_IMU_BRIDGE_IMPL="${ROS2_IMU_BRIDGE_IMPL:-cpp}"

echo "starting C board communication..."

live_standard_robot_pids() {
  local pid stat
  for pid in $(pgrep -x "standard_robot_" 2>/dev/null || true); do
    stat="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
    [[ -n "${stat}" && "${stat}" != Z* ]] && echo "${pid}"
  done
}

if [[ ! -e "${CBOARD_DEVICE}" ]]; then
  echo "warning: ${CBOARD_DEVICE} does not exist. If the board appears as /dev/ttyACM0, run standard_robot_pp_ros2/script/create_udev_rules.sh or update standard_robot_pp_ros2/config/standard_robot_pp_ros2.yaml." >&2
fi

if [[ ! -f "${CBOARD_PARAMS_FILE}" ]]; then
  echo "error: C board parameter file does not exist: ${CBOARD_PARAMS_FILE}" >&2
  exit 1
fi

if pgrep -f "rtt_nav_bridge_node" >/dev/null 2>&1; then
  echo "warning: rtt_nav_bridge_node is running and may occupy the C board serial port." >&2
fi

standard_robot_already_running=false
if [[ -n "$(live_standard_robot_pids)" ]] && ! is_running "$(pid_file standard_robot_pp_ros2)"; then
  echo "warning: unmanaged standard_robot_pp_ros2_node is already running. The script will not start a duplicate serial owner." >&2
  standard_robot_already_running=true
fi

if [[ "${standard_robot_already_running}" != "true" ]]; then
  start_service standard_robot_pp_ros2 \
    bash -lc "unset LD_LIBRARY_PATH; source '${ROS_SETUP}' && source '${QHXD_SETUP}' && cd '${PROJECT_ROOT}' && exec ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py params_file:='${CBOARD_PARAMS_FILE}' use_respawn:='${CBOARD_USE_RESPAWN}'"
fi

start_service ros2_imu_bridge \
  env \
    ROS_SETUP="${ROS_SETUP}" \
    QHXD_SETUP="${QHXD_SETUP}" \
    ROS2_IMU_BRIDGE_IMPL="${ROS2_IMU_BRIDGE_IMPL}" \
    ROS2_IMU_TOPIC="${ROS2_IMU_TOPIC}" \
    ROS2_IMU_BRIDGE_RATE_HZ="${ROS2_IMU_BRIDGE_RATE_HZ}" \
    ROS2_IMU_BRIDGE_SOURCE="${ROS2_IMU_BRIDGE_SOURCE}" \
    ROS2_IMU_BRIDGE_BACKEND_URL="${ROS2_IMU_BRIDGE_BACKEND_URL}" \
    ROS2_IMU_HEARTBEAT_FILE="${ROS2_IMU_HEARTBEAT_FILE}" \
    "${SCRIPT_DIR}/run_imu_bridge.sh"

if [[ "${CBOARD_WATCHDOG_INTERNAL_RESTART:-false}" != "true" && "${CBOARD_WATCHDOG_ENABLED:-false}" == "true" ]]; then
  start_service cboard_watchdog "${SCRIPT_DIR}/run_cboard_watchdog.sh"
fi

echo "C board communication started."
echo "  params_file: ${CBOARD_PARAMS_FILE}"
echo "  use_respawn: ${CBOARD_USE_RESPAWN}"
echo "logs:"
echo "  standard_robot_pp_ros2: $(log_file standard_robot_pp_ros2)"
echo "  ros2_imu_bridge:       $(log_file ros2_imu_bridge)"
echo "  cboard_watchdog:       $(log_file cboard_watchdog)"
