#!/usr/bin/env bash
set -euo pipefail

QHXD_ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
RUNTIME_DIR="$QHXD_ROOT/.runtime"
LOG_DIR="$QHXD_ROOT/logs"
PID_FILE="$RUNTIME_DIR/navigation_web_bridge.pid"
LOG_FILE="$LOG_DIR/navigation_web_bridge.log"
MAP_WATCHDOG_PID_FILE="$RUNTIME_DIR/navigation_web_bridge_map_watchdog.pid"
MAP_WATCHDOG_LOG_FILE="$LOG_DIR/navigation_web_bridge_map_watchdog.log"
BACKEND_PORT="${BACKEND_PORT:-8000}"

if [[ -f "$QHXD_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$QHXD_ROOT/.env"
  set +a
  BACKEND_PORT="${BACKEND_PORT:-8000}"
fi

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
start_map_watchdog() {
  if [[ ! "${QHXD_NAV_WEB_BRIDGE_MAP_WATCHDOG:-true}" =~ ^(1|true|yes|on)$ ]]; then
    return 0
  fi
  if [[ -f "$MAP_WATCHDOG_PID_FILE" ]] && kill -0 "$(cat "$MAP_WATCHDOG_PID_FILE")" 2>/dev/null; then
    return 0
  fi

  (
    set +e
    exec >>"$MAP_WATCHDOG_LOG_FILE" 2>&1
    echo "navigation_web_bridge map watchdog started at $(date)"
    local_wait_seconds="${QHXD_NAV_WEB_BRIDGE_MAP_WAIT_SECONDS:-600}"
    local_interval_seconds="${QHXD_NAV_WEB_BRIDGE_MAP_CHECK_INTERVAL_SECONDS:-5}"
    local_deadline=$((SECONDS + local_wait_seconds))
    while (( SECONDS < local_deadline )); do
      if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/api/navigation/map/metadata" >/dev/null 2>&1; then
        echo "backend already has navigation map metadata; watchdog exiting."
        exit 0
      fi
      if bash -lc "unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source '$QHXD_ROOT/install/setup.bash'; ROS2CLI_DISABLE_DAEMON=1 timeout 4 ros2 topic echo /map --once --field info >/dev/null 2>&1"; then
        echo "ROS /map is available but backend map cache is empty; restarting navigation_web_bridge once."
        QHXD_NAV_WEB_BRIDGE_KEEP_MAP_WATCHDOG=true QHXD_NAV_WEB_BRIDGE_MAP_WATCHDOG=false "$QHXD_ROOT/scripts/stop_navigation_web_bridge.sh"
        QHXD_NAV_WEB_BRIDGE_MAP_WATCHDOG=false "$QHXD_ROOT/scripts/start_navigation_web_bridge.sh"
        sleep 4
        if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/api/navigation/map/metadata" >/dev/null 2>&1; then
          echo "navigation map metadata is now available after bridge restart."
          exit 0
        fi
        echo "navigation map metadata is still unavailable after bridge restart."
        exit 1
      fi
      sleep "$local_interval_seconds"
    done
    echo "watchdog timed out waiting for ROS /map; this is normal when Nav2/map_server is not running."
  ) &
  echo $! >"$MAP_WATCHDOG_PID_FILE"
}

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "navigation_web_bridge is already running (pid $(cat "$PID_FILE"))"
  start_map_watchdog
  exit 0
fi
existing_node="$(pgrep -f '^/home/robomaster/QHXD/install/navigation_web_bridge/lib/navigation_web_bridge/navigation_web_bridge_node ' | head -n 1 || true)"
if [[ -n "$existing_node" ]]; then
  echo "navigation_web_bridge node is already running (pid $existing_node)"
  start_map_watchdog
  exit 0
fi


unset LD_LIBRARY_PATH
set +u
source /opt/ros/humble/setup.bash
source "$QHXD_ROOT/install/setup.bash"
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
start_map_watchdog
