#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${LOG_DIR}/boot_startup.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "========================================"
echo "QHXD Boot Startup - $(date)"
echo "========================================"

# Step 1: Audio init - restore then force
echo "[1/5] Initializing audio..."
alsactl restore >/dev/null 2>&1 || true
# Force ES8388 playback path (Output 1/2 often reset to 0 by alsactl restore)
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

# Step 5: Start YOLO camera
echo "[5/5] Starting YOLO camera service..."
if lsusb 2>/dev/null | grep -qi "Hikrobot"; then
    "${SCRIPT_DIR}/start_yolo_hik_camera.sh" || echo "Hik YOLO start failed."
elif ls /dev/video* 2>/dev/null | grep -q .; then
    "${SCRIPT_DIR}/start_yolo_camera.sh" || echo "USB YOLO start failed."
else
    echo "No camera detected, skipping YOLO."
fi

# Final: re-save ALSA state so next boot starts with correct values
sudo alsactl store 2>/dev/null || true

echo "========================================"
echo "QHXD Boot Startup Complete - $(date)"
echo "========================================"
