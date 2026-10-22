#!/usr/bin/env bash
# 板载离线大模型（rknn-llm，NPU）：OpenAI 兼容接口 127.0.0.1:8080，后端 LLM_BACKEND=local 调用。
# 运行库与模型都不进仓库：scripts/install_rkllm_runtime.sh 装运行库，模型路径写在 .env 的 RKLLM_MODEL_PATH。
set -euo pipefail

ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

: "${RKLLM_MODEL_PATH:?.env 缺少 RKLLM_MODEL_PATH（.rkllm 模型文件）}"
exec "${BACKEND_PYTHON:-python3}" -m yuntuo.llm_server --model "$RKLLM_MODEL_PATH" \
  --lib "${RKLLM_LIB_PATH:-/opt/rkllm/1.3.1/librkllmrt.so}" --port "${RKLLM_PORT:-8080}"
