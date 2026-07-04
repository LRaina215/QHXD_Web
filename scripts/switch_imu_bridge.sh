#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

implementation="${1:-}"
if [[ "${implementation}" != "cpp" && "${implementation}" != "python" ]]; then
  echo "usage: $0 cpp|python" >&2
  exit 2
fi

stop_service ros2_imu_bridge
start_service ros2_imu_bridge \
  env ROS2_IMU_BRIDGE_IMPL="${implementation}" "${SCRIPT_DIR}/run_imu_bridge.sh"

echo "IMU bridge switched to ${implementation}."
status_service ros2_imu_bridge
