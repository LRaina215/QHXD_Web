#!/usr/bin/env bash
set -euo pipefail

ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
unset LD_LIBRARY_PATH
set +u
source /opt/ros/humble/setup.bash
source "$ROOT/install/setup.bash"
source /home/robomaster/livox_ws/install/setup.bash
set -u
exec python3 "$ROOT/scripts/nav2_mission_executor.py"
