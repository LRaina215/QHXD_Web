#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

WIFI_GATEWAY_IP="${WIFI_GATEWAY_IP:-192.168.1.1}"
WIFI_INTERFACE="${WIFI_INTERFACE:-wlan0}"
LIVOX_LIDAR_IP="${LIVOX_LIDAR_IP:-192.168.1.3}"
LIVOX_INTERFACE="${LIVOX_INTERFACE:-eth1}"
LIVOX_HOST_IP="${LIVOX_HOST_IP:-192.168.1.50}"
IP_BIN="${IP_BIN:-$(command -v ip)}"

run_ip_as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "${IP_BIN}" "$@"
  else
    sudo -n "${IP_BIN}" "$@"
  fi
}

run_ip_as_root route add "${WIFI_GATEWAY_IP}/32" dev "${WIFI_INTERFACE}" 2>/dev/null || true

if ! "${IP_BIN}" link show "${LIVOX_INTERFACE}" >/dev/null 2>&1; then
  echo "Livox route skipped: interface ${LIVOX_INTERFACE} not found."
  exit 0
fi

if ! run_ip_as_root route replace "${LIVOX_LIDAR_IP}/32" dev "${LIVOX_INTERFACE}" src "${LIVOX_HOST_IP}"; then
  echo "ERROR: failed to install Livox route; sudo NOPASSWD may be missing." >&2
  exit 1
fi

route_line="$("${IP_BIN}" route get "${LIVOX_LIDAR_IP}" 2>/dev/null || true)"
echo "${route_line}"
if [[ "${route_line}" != *" dev ${LIVOX_INTERFACE} "* ]]; then
  echo "ERROR: Livox route is not using ${LIVOX_INTERFACE}: ${route_line}" >&2
  exit 1
fi

echo "Livox route OK: ${LIVOX_LIDAR_IP} -> ${LIVOX_INTERFACE} src ${LIVOX_HOST_IP}"
