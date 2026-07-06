#!/usr/bin/env bash
set -euo pipefail

QHXD_ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
PID_FILE="$QHXD_ROOT/.runtime/navigation_web_bridge.pid"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
else
  pid=""
fi

if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid"
  for _ in {1..20}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
fi

# Clean up a node orphaned by an older launcher that did not own a process group.
orphan="$(pgrep -f '^/home/robomaster/QHXD/install/navigation_web_bridge/lib/navigation_web_bridge/navigation_web_bridge_node ' | head -n 1 || true)"
if [[ -n "$orphan" ]]; then
  kill -TERM "$orphan" 2>/dev/null || true
fi
rm -f "$PID_FILE"
echo "navigation_web_bridge stopped"
