#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SESSION="${NAV_FRONTEND_TMUX_SESSION:-nav_frontend}"
WORKSPACE="${LIVOX_WS:-/home/robomaster/livox_ws}"
QHXD="${PROJECT_ROOT}"

usage() {
  cat <<'EOF'
Usage: start_navigation_frontend_detached.sh [--attach|--status|--stop]

Start the six-pane Point-LIO navigation front-end tmux session without
attaching to it. This is safe for qhxd-boot.service autostart.
EOF
}

mode="start"
case "${1:-}" in
  "") ;;
  --attach) mode="attach" ;;
  --status) mode="status" ;;
  --stop) mode="stop" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if ! command -v tmux >/dev/null 2>&1; then
  echo "ERROR: tmux is not installed." >&2
  exit 1
fi

stop_frontend_processes() {
  local patterns=(
    "/home/robomaster/livox_ws/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node"
    "/home/robomaster/livox_ws/install/point_lio/lib/point_lio/pointlio_mapping"
    "/home/robomaster/livox_ws/install/loam_interface/lib/loam_interface/loam_interface_node"
    "/home/robomaster/livox_ws/install/sensor_scan_generation/lib/sensor_scan_generation/sensor_scan_generation_node"
    "/opt/ros/humble/lib/pointcloud_to_laserscan/pointcloud_to_laserscan_node"
    "/opt/ros/humble/lib/tf2_ros/static_transform_publisher .*--child-frame-id livox_frame"
    "/opt/ros/humble/bin/ros2 launch /home/robomaster/livox_ws/launch/msg_MID360_pointlio_launch.py"
    "/opt/ros/humble/bin/ros2 run point_lio pointlio_mapping"
    "/opt/ros/humble/bin/ros2 launch /home/robomaster/livox_ws/launch/point_lio_interfaces.launch.py"
    "/opt/ros/humble/bin/ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node"
    "/opt/ros/humble/bin/ros2 run tf2_ros static_transform_publisher .*--child-frame-id livox_frame"
  )
  local pattern
  for pattern in "${patterns[@]}"; do
    pkill -f "${pattern}" 2>/dev/null || true
  done

  # Livox owns several UDP ports. Starting a replacement before the old
  # process has fully exited can yield one frame and then a silent data stall.
  local attempt
  local process_left
  for attempt in $(seq 1 20); do
    process_left=false
    for pattern in "${patterns[@]}"; do
      if pgrep -f "${pattern}" >/dev/null 2>&1; then
        process_left=true
        break
      fi
    done
    if [[ "${process_left}" == false ]]; then
      sleep 2
      return 0
    fi
    sleep 0.5
  done

  echo "navigation front-end processes did not stop cleanly; forcing cleanup"
  for pattern in "${patterns[@]}"; do
    pkill -KILL -f "${pattern}" 2>/dev/null || true
  done
  sleep 2
}

navigation_frontend_healthy() {
  local topic
  local ros_setup="unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source ${WORKSPACE}/install/setup.bash"
  for topic in /livox/lidar /aft_mapped_to_init /sensor_scan /scan; do
    if ! bash -lc "${ros_setup}; ROS2CLI_DISABLE_DAEMON=1 timeout 5 ros2 topic echo '${topic}' --once >/dev/null 2>&1"; then
      echo "navigation front-end health check failed: ${topic} has no live data"
      return 1
    fi
  done
  return 0
}

if [[ "${mode}" == "status" ]]; then
  if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "navigation front-end tmux '${SESSION}': stopped"
    exit 1
  fi
  echo "navigation front-end tmux '${SESSION}': running"
  tmux list-panes -t "${SESSION}:frontend" \
    -F '#{pane_index} #{pane_title}: #{pane_current_command} (dead=#{pane_dead})'
  echo
  echo "actual ROS 2 nodes:"
  bash -lc "unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source '${WORKSPACE}/install/setup.bash' 2>/dev/null || true; ros2 node list 2>/dev/null | sort"
  exit 0
fi

if [[ "${mode}" == "attach" ]]; then
  if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "ERROR: tmux session '${SESSION}' does not exist." >&2
    exit 1
  fi
  exec tmux attach-session -t "${SESSION}"
fi

if [[ "${mode}" == "stop" ]]; then
  if tmux has-session -t "${SESSION}" 2>/dev/null; then
    tmux kill-session -t "${SESSION}"
    echo "navigation front-end tmux '${SESSION}' stopped"
  else
    echo "navigation front-end tmux '${SESSION}' already stopped"
  fi
  stop_frontend_processes
  echo "navigation front-end ROS 2 child processes stopped"
  exit 0
fi

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  "${SCRIPT_DIR}/ensure_livox_route.sh" || true
  if navigation_frontend_healthy; then
    echo "navigation front-end tmux '${SESSION}' is already running and healthy"
    exit 0
  fi
  echo "navigation front-end tmux '${SESSION}' is incomplete; rebuilding all six panes"
  tmux kill-session -t "${SESSION}" 2>/dev/null || true
  stop_frontend_processes
  sleep 2
fi

for required in \
  "${WORKSPACE}/install/setup.bash" \
  "${QHXD}/install/setup.bash" \
  "${WORKSPACE}/launch/msg_MID360_pointlio_launch.py" \
  "${WORKSPACE}/launch/point_lio_interfaces.launch.py" \
  "${WORKSPACE}/config/point_lio_mid360_rk3588.yaml" \
  "${WORKSPACE}/config/mid360_to_scan.yaml"; do
  if [[ ! -e "${required}" ]]; then
    echo "ERROR: required file is missing: ${required}" >&2
    exit 1
  fi
done

"${SCRIPT_DIR}/ensure_livox_route.sh" || true

common_setup="cd ${WORKSPACE}; unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source ${WORKSPACE}/install/setup.bash"
qhxd_setup="cd ${QHXD}; unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source ${QHXD}/install/setup.bash"
ros_setup="unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source ${WORKSPACE}/install/setup.bash"

wait_for_topic_once() {
  local topic="$1"
  local label="$2"
  local timeout_seconds="${3:-20}"
  echo "waiting for ${label} (${topic})..."
  if bash -lc "${ros_setup}; ROS_DISABLE_DAEMON=1 timeout ${timeout_seconds} ros2 topic echo '${topic}' --once >/dev/null 2>&1"; then
    echo "${label} is ready."
    return 0
  fi
  echo "ERROR: timed out waiting for ${label} (${topic})." >&2
  return 1
}

send_pane_command() {
  local pane="$1"
  local command="$2"
  printf -v quoted_command '%q' "${command}"
  tmux send-keys -t "${pane}" "bash -lc ${quoted_command}" C-m
}

commands=(
  "${qhxd_setup}; if pgrep -f '^${QHXD}/install/standard_robot_pp_ros2/lib/standard_robot_pp_ros2/standard_robot_pp_ros2_node( |$)' >/dev/null; then echo 'C board communication is already running; following its log.'; echo 'Ctrl+C here stops log following only, not C board communication.'; exec tail -n 80 -F ${QHXD}/logs/standard_robot_pp_ros2.log; else echo 'Starting C board communication with Point-LIO parameters.'; exec ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py params_file:=${QHXD}/standard_robot_pp_ros2/config/standard_robot_pp_ros2_pointlio.yaml use_respawn:=false; fi"
  "${common_setup}; if pgrep -f '^${WORKSPACE}/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node( |$)' >/dev/null; then echo 'MID360 driver is already running; duplicate start skipped.'; exec bash; else exec ros2 launch ${WORKSPACE}/launch/msg_MID360_pointlio_launch.py; fi"
  "${common_setup}; if pgrep -f '^${WORKSPACE}/install/point_lio/lib/point_lio/pointlio_mapping( |$)' >/dev/null; then echo 'Point-LIO is already running; duplicate start skipped.'; exec bash; else exec ros2 run point_lio pointlio_mapping --ros-args --params-file ${WORKSPACE}/config/point_lio_mid360_rk3588.yaml; fi"
  "${common_setup}; if pgrep -f '^/opt/ros/humble/lib/tf2_ros/static_transform_publisher .*--child-frame-id livox_frame( |$)' >/dev/null; then echo 'base_link -> livox_frame static TF is already running; duplicate start skipped.'; exec bash; else exec ros2 run tf2_ros static_transform_publisher --x 0.0 --y 0.0 --z 0.25 --roll 0.0 --pitch 0.0 --yaw 0.0 --frame-id base_link --child-frame-id livox_frame; fi"
  "${common_setup}; if pgrep -f '^${WORKSPACE}/install/loam_interface/lib/loam_interface/loam_interface_node( |$)' >/dev/null; then echo 'Point-LIO navigation interfaces are already running; duplicate start skipped.'; exec bash; else exec ros2 launch ${WORKSPACE}/launch/point_lio_interfaces.launch.py; fi"
  "${common_setup}; if pgrep -f '^/opt/ros/humble/lib/pointcloud_to_laserscan/pointcloud_to_laserscan_node( |$)' >/dev/null; then echo 'pointcloud_to_laserscan is already running; duplicate start skipped.'; exec bash; else exec ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node --ros-args -r cloud_in:=/sensor_scan -r scan:=/scan --params-file ${WORKSPACE}/config/mid360_to_scan.yaml; fi"
)

titles=(
  "1 CBoard"
  "2 MID360"
  "3 Point-LIO"
  "4 Static-TF"
  "5 LIO-Interfaces"
  "6 LaserScan"
)

tmux new-session -d -s "${SESSION}" -n frontend -c "${WORKSPACE}"
tmux set-option -t "${SESSION}" remain-on-exit on
tmux set-option -t "${SESSION}" pane-border-status top
tmux set-option -t "${SESSION}" pane-border-format ' #{pane_index}: #{pane_title} '

panes=("$(tmux display-message -p -t "${SESSION}:frontend.0" '#{pane_id}')")
for _ in 1 2 3 4 5; do
  panes+=("$(tmux split-window -d -P -F '#{pane_id}' -t "${SESSION}:frontend" -c "${WORKSPACE}")")
  tmux select-layout -t "${SESSION}:frontend" tiled >/dev/null
done

for index in 0 1 2 3 4 5; do
  pane="${panes[${index}]}"
  tmux select-pane -t "${pane}" -T "${titles[${index}]}"
done

send_pane_command "${panes[0]}" "${commands[0]}"
send_pane_command "${panes[1]}" "${commands[1]}"
wait_for_topic_once "/livox/lidar" "MID360 lidar" "${NAV_FRONTEND_WAIT_LIVOX_SECONDS:-25}"

send_pane_command "${panes[2]}" "${commands[2]}"
send_pane_command "${panes[3]}" "${commands[3]}"
send_pane_command "${panes[4]}" "${commands[4]}"
send_pane_command "${panes[5]}" "${commands[5]}"

tmux select-layout -t "${SESSION}:frontend" tiled >/dev/null
tmux select-pane -t "${panes[0]}"

echo "Started six navigation front-end panes in tmux session '${SESSION}'."
echo "Point-LIO and scan topics may take several minutes to become ready; startup continues asynchronously."
echo "Attach with: tmux attach -t ${SESSION}"
