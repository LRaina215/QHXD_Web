#!/usr/bin/env bash
# 云拓感知节点：Astra Pro Plus（UVC 彩色 + OpenNI2 深度）-> RKNN YOLO -> 颜色 / 三维 / 跟踪 -> fpga_bridge 与后端
set -euo pipefail

ROOT="${QHXD_ROOT:-/home/robomaster/QHXD}"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
# Orbbec OpenNI2 SDK 的 libOpenNI2.so 所在目录（例如 /opt/OpenNI2/Redist）
[[ -n "${OPENNI2_REDIST:-}" ]] && export LD_LIBRARY_PATH="$OPENNI2_REDIST${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

ARGS=(--source "${YUNTUO_CAMERA_SOURCE:-astra}" --color-device "${YUNTUO_COLOR_DEVICE:-/dev/yuntuo-astra-color}"
      --detector "${YUNTUO_DETECTOR:-rknn}" --mount "${YUNTUO_CAMERA_MOUNT:-0.20,0,0.30,10,0,0}")
[[ "${YUNTUO_CAMERA_NO_DEPTH:-false}" =~ ^(1|true|yes|on)$ ]] && ARGS+=(--no-depth)

exec "${YOLO_PYTHON:-python3}" -m yuntuo.perception.node "${ARGS[@]}"
