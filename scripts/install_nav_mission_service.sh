#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="qhxd-nav-mission.service"
chmod +x "$ROOT/scripts/nav2_mission_executor.py" "$ROOT/scripts/run_nav2_mission_executor.sh"
sudo install -m 0644 "$ROOT/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE"
sudo systemctl --no-pager --full status "$SERVICE" || true
