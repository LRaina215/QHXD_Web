#!/usr/bin/env bash
# 在 RK3588 上把 QHXD 的 Nav2 链路切换成云拓 FPGA 链路：
#   停用 qhxd-nav-mission（Nav2 任务执行器），安装并启用 yuntuo-fpga-bridge（同一 :9101 契约）与 yuntuo-perception。
# 同时重装 qhxd-boot.service（新版只做音频初始化与切实车模式，不再依赖 Nav2 执行器）；qhxd-backend 不动。
#   --no-perception   不装相机感知
#   --mock-fpga       FPGA 未烧录时装 yuntuo-mock-fpga（.env 里 YUNTUO_FPGA_LINK=udp:127.0.0.1:9000、YUNTUO_FPGA_IS_MOCK=true）
#   --with-llm        装板载离线大模型 yuntuo-llm（需先 scripts/install_rkllm_runtime.sh，.env 设 RKLLM_MODEL_PATH）
#   --with-tts        装板载离线语音合成 yuntuo-tts（pip install --user sherpa-onnx，.env 设 TTS_MODEL_DIR）
# 不带 --mock-fpga 时会停用已装的 yuntuo-mock-fpga（接真 FPGA）。
# 无交互终端时可用 SUDO="sudo -A" + SUDO_ASKPASS。
set -euo pipefail
SUDO="${SUDO:-sudo}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_PERCEPTION=true
MOCK_FPGA=false
WITH_LLM=false
WITH_TTS=false
for arg in "$@"; do
  case "$arg" in
    --no-perception) WITH_PERCEPTION=false ;;
    --mock-fpga) MOCK_FPGA=true ;;
    --with-llm) WITH_LLM=true ;;
    --with-tts) WITH_TTS=true ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

chmod +x "$ROOT"/scripts/run_fpga_bridge.sh "$ROOT"/scripts/run_yuntuo_perception.sh   "$ROOT"/scripts/run_mock_fpga.sh "$ROOT"/scripts/run_yuntuo_llm.sh "$ROOT"/scripts/run_yuntuo_tts.sh

echo "[1/4] 安装 udev 规则（/dev/yuntuo-fpga、/dev/yuntuo-ctl、/dev/yuntuo-astra-color）"
$SUDO install -m 0644 "$ROOT/scripts/udev/99-yuntuo.rules" /etc/udev/rules.d/99-yuntuo.rules
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger
$SUDO usermod -aG dialout,video "$(id -un)" || true

echo "[2/4] 停用 Nav2 任务执行器（qhxd-nav-mission.service）"
if systemctl list-unit-files qhxd-nav-mission.service >/dev/null 2>&1; then
  $SUDO systemctl disable --now qhxd-nav-mission.service || true
fi

echo "[3/4] 安装云拓服务"
$SUDO install -m 0644 "$ROOT/systemd/yuntuo-fpga-bridge.service" /etc/systemd/system/yuntuo-fpga-bridge.service
if [[ "$WITH_PERCEPTION" == true ]]; then
  $SUDO install -m 0644 "$ROOT/systemd/yuntuo-perception.service" /etc/systemd/system/yuntuo-perception.service
fi
[[ "$MOCK_FPGA" == true ]] && $SUDO install -m 0644 "$ROOT/systemd/yuntuo-mock-fpga.service" /etc/systemd/system/yuntuo-mock-fpga.service
[[ "$WITH_LLM" == true ]] && $SUDO install -m 0644 "$ROOT/systemd/yuntuo-llm.service" /etc/systemd/system/yuntuo-llm.service
[[ "$WITH_TTS" == true ]] && $SUDO install -m 0644 "$ROOT/systemd/yuntuo-tts.service" /etc/systemd/system/yuntuo-tts.service
$SUDO install -m 0644 "$ROOT/systemd/qhxd-boot.service" /etc/systemd/system/qhxd-boot.service
$SUDO systemctl daemon-reload
$SUDO systemctl enable qhxd-boot.service
if [[ "$MOCK_FPGA" == true ]]; then
  $SUDO systemctl enable --now yuntuo-mock-fpga.service
elif systemctl list-unit-files yuntuo-mock-fpga.service >/dev/null 2>&1; then
  $SUDO systemctl disable --now yuntuo-mock-fpga.service || true
fi
$SUDO systemctl enable yuntuo-fpga-bridge.service
$SUDO systemctl restart yuntuo-fpga-bridge.service
if [[ "$WITH_PERCEPTION" == true ]]; then
  $SUDO systemctl enable yuntuo-perception.service
  $SUDO systemctl restart yuntuo-perception.service
fi
if [[ "$WITH_LLM" == true ]]; then
  $SUDO systemctl enable yuntuo-llm.service
  $SUDO systemctl restart yuntuo-llm.service
fi
if [[ "$WITH_TTS" == true ]]; then
  $SUDO systemctl enable yuntuo-tts.service
  $SUDO systemctl restart yuntuo-tts.service
fi

echo "[4/4] 检查"
sleep 3
curl --noproxy '*' -fsS http://127.0.0.1:9101/health && echo || echo "fpga_bridge /health 未就绪：sudo journalctl -u yuntuo-fpga-bridge -n 80 --no-pager"
if [[ "$WITH_LLM" == true ]]; then
  for _ in $(seq 1 20); do curl --noproxy '*' -fsS http://127.0.0.1:8080/health >/dev/null 2>&1 && break; sleep 1; done
  curl --noproxy '*' -fsS http://127.0.0.1:8080/health && echo || echo "yuntuo-llm 未就绪：sudo journalctl -u yuntuo-llm -n 80 --no-pager"
fi
if [[ "$WITH_TTS" == true ]]; then
  for _ in $(seq 1 20); do curl --noproxy '*' -fsS http://127.0.0.1:8081/health >/dev/null 2>&1 && break; sleep 1; done
  curl --noproxy '*' -fsS http://127.0.0.1:8081/health && echo || echo "yuntuo-tts 未就绪：sudo journalctl -u yuntuo-tts -n 80 --no-pager"
fi
grep -q 'config/yuntuo/waypoints.json' "$ROOT/.env" 2>/dev/null || echo "提醒：$ROOT/.env 请以 .env.example 为模板重写，WAYPOINTS_CONFIG_PATH / PATROL_ROUTES_CONFIG_PATH 指向 backend/app/config/yuntuo/。"
