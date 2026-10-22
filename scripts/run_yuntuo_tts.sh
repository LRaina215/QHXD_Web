#!/usr/bin/env bash
# 板载离线语音合成（sherpa-onnx，CPU）：POST 127.0.0.1:8081/tts，后端 TTS_BACKEND=local + TTS_LOCAL_URL 调用。
# 模型不进仓库，目录写在 .env 的 TTS_MODEL_DIR / TTS_VOCODER_PATH（见 docs/YUNTUO.md 离线语音一节）。
set -euo pipefail

ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

: "${TTS_MODEL_DIR:?.env 缺少 TTS_MODEL_DIR}"
exec "${BACKEND_PYTHON:-python3}" -m yuntuo.tts_server
