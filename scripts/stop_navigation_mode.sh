#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SESSION="${QHXD_NAV_MODE_TMUX_SESSION:-nav_mode}"
INITIAL_POSE_PID_FILE="${RUNTIME_DIR}/navigation_initial_pose.pid"

if [[ -f "${INITIAL_POSE_PID_FILE}" ]]; then
  initial_pose_pid="$(cat "${INITIAL_POSE_PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${initial_pose_pid}" ]] && kill -0 "${initial_pose_pid}" 2>/dev/null; then
    kill "${initial_pose_pid}" 2>/dev/null || true
  fi
  rm -f "${INITIAL_POSE_PID_FILE}"
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed; nothing to stop"
  exit 0
fi

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  tmux kill-session -t "${SESSION}"
  echo "navigation mode tmux '${SESSION}' stopped"
else
  echo "navigation mode tmux '${SESSION}' already stopped"
fi
