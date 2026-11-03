#!/usr/bin/env bash
# 默认只观察真实后端请求。旧独立问答链仅在显式 --standalone 时启动。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRY=observe_ai_pipeline.py
if [[ "${1:-}" == --standalone ]]; then
  ENTRY=ai_demo_terminals.py
  shift
fi
exec "${AI_DEMO_PYTHON:-python3}" -u "${SCRIPT_DIR}/${ENTRY}" "$@"
