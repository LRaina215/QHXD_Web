#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SESSION="${QHXD_NAV_MODE_TMUX_SESSION:-nav_mode}"

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
