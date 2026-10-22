#!/usr/bin/env bash
# 安装 Orbbec 版 OpenNI2（含 liborbbec.so 驱动）到 /opt/OpenNI2/Redist，供 Astra Pro Plus 深度流使用。
# Ubuntu 自带的 libopenni2 不认 Orbbec 设备（VID 2bc5），所以单独装一份，不替换系统库。
# 来源：github.com/orbbec/ros2_astra_camera 的 astra_camera/openni2_redist/<arch>（厂商二进制，不放进本仓库）。
set -euo pipefail

DEST="${OPENNI2_REDIST:-/opt/OpenNI2/Redist}"
SUDO="${SUDO:-sudo}"   # 非交互执行时可设 SUDO="sudo -A" 配合 SUDO_ASKPASS
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64) SUB=arm64 ;;
  x86_64) SUB=x64 ;;
  *) echo "不支持的架构：$ARCH" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/orbbec/ros2_astra_camera.git "$TMP/repo"
git -C "$TMP/repo" sparse-checkout set "astra_camera/openni2_redist/$SUB" astra_camera/scripts
SRC="$TMP/repo/astra_camera/openni2_redist/$SUB"
REV="$(git -C "$TMP/repo" rev-parse --short HEAD)"

$SUDO mkdir -p "$DEST/OpenNI2/Drivers"
$SUDO install -m 0755 "$SRC/libOpenNI2.so" "$DEST/libOpenNI2.so"
$SUDO install -m 0644 "$SRC/OpenNI.ini" "$DEST/OpenNI.ini"
for f in "$SRC"/OpenNI2/Drivers/*; do
  case "$f" in
    *.so) $SUDO install -m 0755 "$f" "$DEST/OpenNI2/Drivers/" ;;
    *) $SUDO install -m 0644 "$f" "$DEST/OpenNI2/Drivers/" ;;
  esac
done
echo "Orbbec OpenNI2 $SUB redist from github.com/orbbec/ros2_astra_camera@$REV" | $SUDO tee "$DEST/SOURCE.txt" >/dev/null

# 设备权限：深度走 libusb（需要普通用户可读写），彩色走 UVC（/dev/yuntuo-astra-color，见 udev/99-yuntuo.rules）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
$SUDO install -m 0644 "$ROOT/scripts/udev/99-yuntuo.rules" /etc/udev/rules.d/99-yuntuo.rules
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger --subsystem-match=usb --subsystem-match=video4linux

python3 -m pip install --user -q -r "$ROOT/yuntuo/requirements.txt"
echo "已安装到 $DEST（来源 ros2_astra_camera@$REV）"
python3 - <<'EOF'
from openni import openni2
openni2.initialize("/opt/OpenNI2/Redist")
print("OpenNI2 设备：", openni2.Device.enumerate_uris() or "未发现（检查 USB 连接）")
openni2.unload()
EOF
