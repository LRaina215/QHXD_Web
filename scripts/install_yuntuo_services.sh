#!/usr/bin/env bash
# 在 RK3588 上把 QHXD 的 Nav2 链路切换成云拓 FPGA 链路：
#   停用 qhxd-nav-mission（Nav2 任务执行器），安装并启用 yuntuo-fpga-bridge（同一 :9101 契约）与 yuntuo-perception。
# 后端 qhxd-backend 与开机脚本 qhxd-boot 保留；.env 里需要 YUNTUO_MODE=true，开机脚本才会跳过 C 板 / Nav2 / 旧相机服务。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_PERCEPTION=true
[[ "${1:-}" == "--no-perception" ]] && WITH_PERCEPTION=false

chmod +x "$ROOT/scripts/run_fpga_bridge.sh" "$ROOT/scripts/run_yuntuo_perception.sh"

echo "[1/4] 安装 udev 规则（/dev/yuntuo-fpga、/dev/yuntuo-ctl、/dev/yuntuo-astra-color）"
sudo install -m 0644 "$ROOT/scripts/udev/99-yuntuo.rules" /etc/udev/rules.d/99-yuntuo.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG dialout,video "$(id -un)" || true

echo "[2/4] 停用 Nav2 任务执行器（qhxd-nav-mission.service）"
if systemctl list-unit-files qhxd-nav-mission.service >/dev/null 2>&1; then
  sudo systemctl disable --now qhxd-nav-mission.service || true
fi

echo "[3/4] 安装云拓服务"
sudo install -m 0644 "$ROOT/systemd/yuntuo-fpga-bridge.service" /etc/systemd/system/yuntuo-fpga-bridge.service
if [[ "$WITH_PERCEPTION" == true ]]; then
  sudo install -m 0644 "$ROOT/systemd/yuntuo-perception.service" /etc/systemd/system/yuntuo-perception.service
fi
sudo systemctl daemon-reload
sudo systemctl enable --now yuntuo-fpga-bridge.service
[[ "$WITH_PERCEPTION" == true ]] && sudo systemctl enable --now yuntuo-perception.service

echo "[4/4] 检查"
sleep 3
curl --noproxy '*' -fsS http://127.0.0.1:9101/health && echo || echo "fpga_bridge /health 未就绪：sudo journalctl -u yuntuo-fpga-bridge -n 80 --no-pager"
grep -q '^YUNTUO_MODE=true' "$ROOT/.env" 2>/dev/null || echo "提醒：在 $ROOT/.env 中加入 YUNTUO_MODE=true（开机跳过 C 板 / Nav2 / 旧相机），以及 WAYPOINTS_CONFIG_PATH 指向 backend/app/config/yuntuo/。"
