#!/usr/bin/env bash
# 云拓开机脚本（qhxd-boot.service）：音频初始化、等后端就绪、切到实车模式。
# fpga_bridge 与感知节点是独立的 systemd 服务（yuntuo-fpga-bridge / yuntuo-perception），不在这里拉起。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${LOG_DIR}/boot_startup.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "========================================"
echo "YunTuo Boot Startup - $(date)"
echo "========================================"

echo "[1/3] Initializing audio..."
# 直接用 ALSA（AUDIO_DEVICE / TTS_PLAYER_CMD），不能让桌面或 SSH 会话的 PulseAudio 占住麦克风和 ES8388 喇叭
systemctl --user stop pulseaudio.socket pulseaudio.service >/dev/null 2>&1 || true
pulseaudio --kill >/dev/null 2>&1 || true
alsactl restore >/dev/null 2>&1 || true
amixer -c 2 sset Speaker on >/dev/null 2>&1 || true
amixer -c 2 sset Headphone on >/dev/null 2>&1 || true
amixer -c 2 sset PCM 95% >/dev/null 2>&1 || true
amixer -c 2 sset 'Output 1' 90% >/dev/null 2>&1 || true
amixer -c 2 sset 'Output 2' 90% >/dev/null 2>&1 || true
echo "Audio initialized."

echo "[2/3] Waiting for backend..."
for _ in $(seq 1 30); do
    if curl -s --noproxy "*" "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
        echo "Backend is healthy."
        break
    fi
    sleep 2
done

echo "[3/3] Switching to real mode..."
curl -s -X POST "http://127.0.0.1:${BACKEND_PORT}/api/system/mode/switch" \
    -H "Content-Type: application/json" \
    -d '{"mode":"real","source":"boot-startup"}' >/dev/null 2>&1 || true
echo "Real mode switch sent."

sudo -n alsactl store 2>/dev/null || true

echo "========================================"
echo "YunTuo Boot Startup Complete - $(date)"
echo "========================================"
