#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
"${SCRIPT_DIR}/start_yuntuo_sim.sh" stop
stop_service frontend
stop_service backend
