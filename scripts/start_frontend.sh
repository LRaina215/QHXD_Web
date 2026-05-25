#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
if command -v curl >/dev/null 2>&1 && curl --noproxy '*' -fsS "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null; then
  echo "frontend already reachable: http://127.0.0.1:${FRONTEND_PORT}"
  exit 0
fi
cd "${PROJECT_ROOT}/frontend"
if [[ ! -d node_modules ]]; then
  echo "frontend/node_modules missing; run npm install in frontend first." >&2
  exit 1
fi
start_service frontend npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}"
echo "frontend URL: http://127.0.0.1:${FRONTEND_PORT}"
