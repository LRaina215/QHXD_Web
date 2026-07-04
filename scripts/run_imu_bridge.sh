#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
QHXD_SETUP="${QHXD_SETUP:-${PROJECT_ROOT}/install/setup.bash}"
ROS2_IMU_BRIDGE_IMPL="${ROS2_IMU_BRIDGE_IMPL:-cpp}"
ROS2_IMU_TOPIC="${ROS2_IMU_TOPIC:-/serial/imu_backend}"
ROS2_IMU_BRIDGE_RATE_HZ="${ROS2_IMU_BRIDGE_RATE_HZ:-20}"
ROS2_IMU_BRIDGE_SOURCE="${ROS2_IMU_BRIDGE_SOURCE:-rk3588_cboard_ros2}"
ROS2_IMU_BRIDGE_BACKEND_URL="${ROS2_IMU_BRIDGE_BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"
ROS2_IMU_HEARTBEAT_FILE="${ROS2_IMU_HEARTBEAT_FILE:-${RUNTIME_DIR}/ros2_imu_bridge.heartbeat}"
rate_hz_value="${ROS2_IMU_BRIDGE_RATE_HZ}"
if [[ "${rate_hz_value}" != *.* ]]; then
  rate_hz_value="${rate_hz_value}.0"
fi

set +u
source "${ROS_SETUP}"
source "${QHXD_SETUP}"
set -u
cd "${PROJECT_ROOT}"

case "${ROS2_IMU_BRIDGE_IMPL}" in
  cpp)
    executable="${PROJECT_ROOT}/install/standard_robot_pp_ros2/lib/standard_robot_pp_ros2/imu_backend_bridge_node"
    if [[ ! -x "${executable}" ]]; then
      echo "C++ IMU bridge is not installed: ${executable}" >&2
      echo "Build it first or set ROS2_IMU_BRIDGE_IMPL=python." >&2
      exit 1
    fi
    exec "${executable}" --ros-args \
      -p "topic:=${ROS2_IMU_TOPIC}" \
      -p "backend_url:=${ROS2_IMU_BRIDGE_BACKEND_URL}" \
      -p "source:=${ROS2_IMU_BRIDGE_SOURCE}" \
      -p "rate_hz:=${rate_hz_value}" \
      -p "heartbeat_file:=${ROS2_IMU_HEARTBEAT_FILE}"
    ;;
  python)
    exec python3 scripts/ros2_imu_bridge.py \
      --topic "${ROS2_IMU_TOPIC}" \
      --backend-url "${ROS2_IMU_BRIDGE_BACKEND_URL}" \
      --source "${ROS2_IMU_BRIDGE_SOURCE}" \
      --rate-hz "${ROS2_IMU_BRIDGE_RATE_HZ}" \
      --heartbeat-file "${ROS2_IMU_HEARTBEAT_FILE}"
    ;;
  *)
    echo "Unsupported ROS2_IMU_BRIDGE_IMPL=${ROS2_IMU_BRIDGE_IMPL}; use cpp or python." >&2
    exit 2
    ;;
esac
