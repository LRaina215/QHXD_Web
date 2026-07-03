#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${LOG_DIR}/boot_startup.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "========================================"
echo "QHXD Boot Startup - $(date)"
echo "========================================"

# Step 1: Audio init
echo "[1/5] Initializing audio..."
# Direct ALSA is required by AUDIO_DEVICE/TTS_PLAYER_CMD. A desktop or SSH
# user session must not let PulseAudio claim the USB mic or ES8388 speaker.
systemctl --user stop pulseaudio.socket pulseaudio.service >/dev/null 2>&1 || true
pulseaudio --kill >/dev/null 2>&1 || true
alsactl restore >/dev/null 2>&1 || true
amixer -c 2 sset Speaker on >/dev/null 2>&1 || true
amixer -c 2 sset Headphone on >/dev/null 2>&1 || true
amixer -c 2 sset PCM 95% >/dev/null 2>&1 || true
amixer -c 2 sset 'Output 1' 90% >/dev/null 2>&1 || true
amixer -c 2 sset 'Output 2' 90% >/dev/null 2>&1 || true
echo "Audio initialized."

# Step 2: Wait for backend
echo "[2/5] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s --noproxy "*" "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
        echo "Backend is healthy."
        break
    fi
    sleep 2
done

# Step 3: Switch to real mode
echo "[3/5] Switching to real mode..."
curl -s -X POST "http://127.0.0.1:${BACKEND_PORT}/api/system/mode/switch" \
    -H "Content-Type: application/json" \
    -d '{"mode":"real","source":"boot-startup"}' >/dev/null 2>&1 || true
echo "Real mode switch sent."

# Step 4: Start C board communication
echo "[4/5] Starting C board communication..."
"${SCRIPT_DIR}/start_cboard_comm.sh" || echo "C board communication start failed (no C board connected?)"

# Step 5: Start YOLO camera with retry logic
echo "[5/5] Starting YOLO camera service..."
CAMERA_STARTED=false

for attempt in 1 2 3; do
    echo "  Camera attempt ${attempt}/3..."
    
    if lsusb 2>/dev/null | grep -Eqi "Hikrobot|(^|[[:space:]])2bdf:"; then
        echo "  Hik camera detected."
        "${SCRIPT_DIR}/start_yolo_hik_camera.sh" && CAMERA_STARTED=true && break
        echo "  Hik YOLO start failed, retrying..."
        sleep 3
    elif [[ -e /dev/qhxd-usb-camera ]]; then
        echo "  USB camera detected at /dev/qhxd-usb-camera."
        "${SCRIPT_DIR}/start_yolo_camera.sh" && CAMERA_STARTED=true && break
        echo "  USB YOLO start failed, retrying..."
        sleep 3
    else
        echo "  No camera detected on attempt ${attempt}."
        sleep 5
    fi
done

if [ "${CAMERA_STARTED}" = true ]; then
    echo "  YOLO camera started successfully."
else
    echo "  WARNING: Could not start YOLO camera after 3 attempts."
    echo "  Run: cd ~/QHXD && ./scripts/start_yolo_hik_camera.sh"
fi

# Final: save ALSA state
sudo alsactl store 2>/dev/null || true

echo "========================================"
echo "QHXD Boot Startup Complete - $(date)"
echo "========================================"
