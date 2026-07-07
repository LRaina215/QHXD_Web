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

if systemctl list-unit-files qhxd-nav-mission.service >/dev/null 2>&1; then
  echo "systemd Nav2 mission executor: $(systemctl is-active qhxd-nav-mission.service 2>/dev/null || true)"
  echo "Nav2 mission executor enabled: $(systemctl is-enabled qhxd-nav-mission.service 2>/dev/null || true)"
else
  echo "systemd Nav2 mission executor: not installed"
fi

if is_running "$(pid_file backend)"; then
  echo "PID debug backend: running pid=$(cat "$(pid_file backend)") log=$(log_file backend)"
else
  echo "PID debug backend: not running (normal when systemd backend is active)"
fi
echo

if command -v curl >/dev/null 2>&1; then
  if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
    echo "local backend /health: OK"
  else
    echo "local backend /health: unavailable"
  fi
  if curl --noproxy '*' -fsS "http://127.0.0.1:${NAV_MISSION_EXECUTOR_PORT:-9101}/health" >/dev/null; then
    echo "Nav2 mission executor /health: OK"
  else
    echo "Nav2 mission executor /health: unavailable"
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
bridge_pid_file="$(pid_file ros2_imu_bridge)"
if is_running "${bridge_pid_file}"; then
  bridge_pid="$(cat "${bridge_pid_file}")"
  bridge_command="$(tr '\0' ' ' <"/proc/${bridge_pid}/cmdline" 2>/dev/null || true)"
  if [[ "${bridge_command}" == *imu_backend_bridge_node* ]]; then
    echo "ros2_imu_bridge implementation: cpp"
  elif [[ "${bridge_command}" == *ros2_imu_bridge.py* ]]; then
    echo "ros2_imu_bridge implementation: python"
  fi
fi
status_service cboard_watchdog

if [[ "${QHXD_VIDEO_STREAM_ENABLED:-false}" =~ ^(1|true|yes|on)$ ]]; then
  echo "H.264 cloud publisher: enabled"
  publisher_log="$(log_file yolo_camera)"
  if [[ -f "${publisher_log}" ]] && grep -q "H.264 stream publisher connected" "${publisher_log}"; then
    echo "H.264 cloud publisher: connected"
  else
    echo "H.264 cloud publisher: waiting/reconnecting"
  fi
else
  echo "H.264 cloud publisher: disabled"
fi

if command -v ros2 >/dev/null 2>&1; then
  echo
  echo "ROS 2 topics:"
  bash -lc "source /opt/ros/humble/setup.bash && source '${PROJECT_ROOT}/install/setup.bash' 2>/dev/null || true; ros2 topic list 2>/dev/null | sort | grep -E '^/(cmd_vel|odom|serial/imu|serial/imu_backend|serial/robot_motion)$' || true"
fi
