#!/usr/bin/env bash
# 在 RK 的图形桌面执行；不需 sudo，也不停止任何业务服务。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${AI_DEMO_PYTHON:-python3}" -u "${SCRIPT_DIR}/ai_demo_terminals.py" "$@"
