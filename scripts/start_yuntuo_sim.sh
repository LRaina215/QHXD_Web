#!/usr/bin/env bash
# 不上实车的联调：mock_fpga（模拟 FPGA 导航 + 虚拟相机 + 控制遥测）+ fpga_bridge。后端需已运行（:8000）。
#   ./scripts/start_yuntuo_sim.sh          启动
#   ./scripts/start_yuntuo_sim.sh stop     停止
# 网页切到"实车"模式即可看到模拟数据（链路显示"模拟"）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.runtime"
LOG="$ROOT/logs"
PY="${BACKEND_PYTHON:-python3}"
mkdir -p "$RUN" "$LOG"

stop_one() {
  local f="$RUN/$1.pid"
  [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null || true
  rm -f "$f"
}

if [[ "${1:-}" == "stop" ]]; then
  stop_one yuntuo_sim_bridge
  stop_one yuntuo_sim_fpga
  echo "已停止模拟链路"
  exit 0
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
FRAME="${PERCEPTION_LATEST_FRAME_PATH:-$ROOT/experiments/rknn_yolo/outputs/latest_camera_detection.jpg}"
nohup "$PY" -m yuntuo.mock_fpga --camera-udp 127.0.0.1:9102 --telemetry-udp 127.0.0.1:9104 \
  --backend "http://127.0.0.1:${BACKEND_PORT:-8000}" --frame-out "$FRAME" >"$LOG/yuntuo_sim_fpga.log" 2>&1 &
echo $! >"$RUN/yuntuo_sim_fpga.pid"
sleep 1
YUNTUO_FPGA_IS_MOCK=true WAYPOINTS_CONFIG_PATH="${WAYPOINTS_CONFIG_PATH:-$ROOT/backend/app/config/yuntuo/waypoints.json}" \
PATROL_ROUTES_CONFIG_PATH="${PATROL_ROUTES_CONFIG_PATH:-$ROOT/backend/app/config/yuntuo/patrol_routes.json}" \
nohup "$PY" -m yuntuo.fpga_bridge --link udp:127.0.0.1:9000 --mock --telemetry udp:127.0.0.1:9104 \
  >"$LOG/yuntuo_sim_bridge.log" 2>&1 &
echo $! >"$RUN/yuntuo_sim_bridge.pid"
sleep 2
curl --noproxy '*' -fsS http://127.0.0.1:9101/health >/dev/null && echo "模拟链路已启动：fpga_bridge :9101，日志 $LOG/yuntuo_sim_*.log" \
  || echo "fpga_bridge 未就绪，查看 $LOG/yuntuo_sim_bridge.log"
