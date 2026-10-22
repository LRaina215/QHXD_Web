#!/usr/bin/env bash
# 安装 rknn-llm 运行库到 /opt/rkllm/<版本>/（不覆盖系统里已有的 /usr/lib/librkllmrt.so）。
#   ./scripts/install_rkllm_runtime.sh                       从 GitHub 下载 release-v1.3.1 的 aarch64 运行库
#   ./scripts/install_rkllm_runtime.sh /path/librkllmrt.so   板子上不了 GitHub 时，用电脑上下好的文件
# 运行库来自 https://github.com/airockchip/rknn-llm （Rockchip 版权，不进本仓库）。
# 模型（.rkllm）需与运行库版本匹配：RKNNAI 发布的 Qwen2.5-1.5B-Instruct（toolkit 1.2.4）已在 1.3.1 上验证可用。
set -euo pipefail

VERSION="${RKLLM_VERSION:-1.3.1}"
DEST="/opt/rkllm/$VERSION"
URL="https://raw.githubusercontent.com/airockchip/rknn-llm/release-v$VERSION/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
SUDO="${SUDO:-sudo}"

src="${1:-}"
tmp=""
if [[ -z "$src" ]]; then
  tmp="$(mktemp)"
  echo "下载 $URL"
  curl -fL --retry 3 -m 600 -o "$tmp" "$URL" || { echo "下载失败：在电脑上下载后用参数传入文件路径" >&2; rm -f "$tmp"; exit 1; }
  src="$tmp"
fi
[[ -f "$src" ]] || { echo "找不到 $src" >&2; exit 1; }
file "$src" | grep -q "ARM aarch64" || { echo "$src 不是 aarch64 动态库" >&2; exit 1; }

$SUDO mkdir -p "$DEST"
$SUDO install -m 0644 "$src" "$DEST/librkllmrt.so"
printf 'rknn-llm release-v%s\n%s\nmd5 %s\ninstalled %s\n' "$VERSION" "$URL" "$(md5sum "$DEST/librkllmrt.so" | cut -d' ' -f1)" \
  "$(date -Iseconds)" | $SUDO tee "$DEST/SOURCE.txt" >/dev/null
[[ -n "$tmp" ]] && rm -f "$tmp"
strings "$DEST/librkllmrt.so" | grep -q "rkllm-runtime version" && echo "已安装：$DEST/librkllmrt.so"
echo "NPU 驱动：$($SUDO cat /sys/kernel/debug/rknpu/version 2>/dev/null || echo 未知)（低于 0.9.7 会有警告，0.9.6 实测可用）"
