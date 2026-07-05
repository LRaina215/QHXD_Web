#!/usr/bin/env bash
set -euo pipefail

QHXD_ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
LIVOX_WS="${LIVOX_WS:-/home/robomaster/livox_ws}"
RUNTIME_DIR="$QHXD_ROOT/.runtime"
PID_FILE="$RUNTIME_DIR/navigation_web_bridge.pid"
LOG_FILE="$RUNTIME_DIR/navigation_web_bridge.log"

mkdir -p "$RUNTIME_DIR"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "navigation_web_bridge is already running (pid $(cat "$PID_FILE"))"
  exit 0
fi
existing_node="$(pgrep -f '^/home/robomaster/livox_ws/install/navigation_web_bridge/lib/navigation_web_bridge/navigation_web_bridge_node ' | head -n 1 || true)"
if [[ -n "$existing_node" ]]; then
  echo "navigation_web_bridge node is already running (pid $existing_node)"
  exit 0
fi

unset LD_LIBRARY_PATH
set +u
source /opt/ros/humble/setup.bash
source "$LIVOX_WS/install/setup.bash"
set -u

nohup setsid ros2 launch navigation_web_bridge navigation_web_bridge.launch.py \
  >"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"
sleep 1

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "navigation_web_bridge failed to start; see $LOG_FILE" >&2
  exit 1
fi
echo "navigation_web_bridge started (pid $(cat "$PID_FILE")); log: $LOG_FILE"
