#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SERVICE_NAME="qhxd-backend.service"
PUBLIC_API_HEALTH_URL="${PUBLIC_API_HEALTH_URL:-https://api.lingxunrobot.cn/health}"
PUBLIC_WEB_URL="${PUBLIC_WEB_URL:-https://lingxunrobot.cn}"
PUBLIC_STATE_URL="${PUBLIC_STATE_URL:-https://lingxunrobot.cn/api/state/latest}"

echo "QHXD public robot status"
echo "project: ${PROJECT_ROOT}"
echo

if systemctl list-unit-files "${SERVICE_NAME}" >/dev/null 2>&1; then
  echo "systemd backend: $(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"
  echo "systemd enabled: $(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
else
  echo "systemd backend: not installed"
fi

status_service backend
echo

if command -v curl >/dev/null 2>&1; then
  if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
    echo "local backend /health: OK"
  else
    echo "local backend /health: unavailable"
  fi

  if curl -fsS --max-time 8 "${PUBLIC_API_HEALTH_URL}" >/dev/null 2>&1; then
    echo "public gateway health: OK (${PUBLIC_API_HEALTH_URL})"
  else
    echo "public gateway health: unavailable (${PUBLIC_API_HEALTH_URL})"
  fi

  if curl -fsS -I --max-time 8 "${PUBLIC_WEB_URL}" >/dev/null 2>&1; then
    echo "public web: OK (${PUBLIC_WEB_URL})"
  else
    echo "public web: unavailable (${PUBLIC_WEB_URL})"
  fi

  if curl -fsS --max-time 8 "${PUBLIC_STATE_URL}" >/dev/null 2>&1; then
    echo "public state proxy: OK (${PUBLIC_STATE_URL})"
  else
    echo "public state proxy: unavailable (${PUBLIC_STATE_URL})"
  fi
fi

if command -v tailscale >/dev/null 2>&1; then
  echo
  echo "tailscale ip: $(tailscale ip -4 2>/dev/null | head -1 || true)"
fi

echo
echo "Optional local services:"
status_service frontend
status_service yolo_camera
status_service standard_robot_pp_ros2
status_service ros2_imu_bridge

if command -v ros2 >/dev/null 2>&1; then
  echo
  echo "ROS 2 topics:"
  bash -lc "source /opt/ros/humble/setup.bash && source '${PROJECT_ROOT}/install/setup.bash' 2>/dev/null || true; ros2 topic list 2>/dev/null | sort | grep -E '^/(cmd_vel|odom|serial/imu|serial/robot_motion)$' || true"
fi
