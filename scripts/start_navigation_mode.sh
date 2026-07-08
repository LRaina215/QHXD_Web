#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SESSION="${QHXD_NAV_MODE_TMUX_SESSION:-nav_mode}"
WORKSPACE="${LIVOX_WS:-/home/robomaster/livox_ws}"
MODE="${1:-${QHXD_BOOT_NAV_MODE:-none}}"

usage() {
  cat <<'EOF'
Usage: start_navigation_mode.sh <none|mapping|slam|localization|navigation|nav|bringup> [--attach]
       start_navigation_mode.sh --status

Run exactly one navigation mode in tmux. Do not run mapping and AMCL/Nav2 at
the same time because both can own map -> odom.
EOF
}

attach_after_start=false
case "${2:-}" in
  "") ;;
  --attach) attach_after_start=true ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

case "${MODE}" in
  -h|--help) usage; exit 0 ;;
  --status|status)
    if tmux has-session -t "${SESSION}" 2>/dev/null; then
      echo "navigation mode tmux '${SESSION}': running"
      tmux list-windows -t "${SESSION}" -F '#{window_index}: #{window_name} #{window_active}'
      tmux list-panes -t "${SESSION}" -F '#{pane_index}: #{pane_current_command} (dead=#{pane_dead})'
      exit 0
    fi
    echo "navigation mode tmux '${SESSION}': stopped"
    exit 1
    ;;
esac

if [[ "${MODE}" =~ ^(none|off|false|0)$ ]]; then
  echo "navigation mode autostart disabled (mode=${MODE})"
  exit 0
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "ERROR: tmux is not installed." >&2
  exit 1
fi

if [[ ! -e "${WORKSPACE}/install/setup.bash" ]]; then
  echo "ERROR: missing livox workspace setup: ${WORKSPACE}/install/setup.bash" >&2
  exit 1
fi

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "navigation mode tmux '${SESSION}' already running; stop it before switching modes."
  exit 0
fi

common_setup="cd ${WORKSPACE}; unset LD_LIBRARY_PATH; source /opt/ros/humble/setup.bash; source ${WORKSPACE}/install/setup.bash"
case "${MODE}" in
  mapping|slam)
    MODE="mapping"
    command="${common_setup}; exec ros2 launch slam_toolbox online_sync_launch.py slam_params_file:=${WORKSPACE}/config/slam_toolbox_mid360.yaml"
    ;;
  localization|amcl)
    MODE="localization"
    command="${common_setup}; exec ros2 launch rk3588_navigation localization.launch.py"
    ;;
  navigation|nav)
    MODE="navigation"
    command="${common_setup}; exec ros2 launch rk3588_navigation navigation.launch.py"
    ;;
  bringup)
    command="${common_setup}; exec ros2 launch rk3588_navigation bringup.launch.py"
    ;;
  *)
    echo "ERROR: unsupported navigation mode: ${MODE}" >&2
    usage >&2
    exit 2
    ;;
esac

printf -v quoted_command '%q' "${command}"
tmux new-session -d -s "${SESSION}" -n "${MODE}" -c "${WORKSPACE}" "bash -lc ${quoted_command}"
tmux set-option -t "${SESSION}" remain-on-exit on

echo "navigation mode '${MODE}' started in tmux session '${SESSION}'."
echo "Attach with: tmux attach -t ${SESSION}"

if [[ "${attach_after_start}" == true ]]; then
  exec tmux attach-session -t "${SESSION}"
fi
