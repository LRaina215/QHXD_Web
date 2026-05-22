#!/usr/bin/env bash
set -euo pipefail

ALIAS_NAME="${USB_CAMERA_ALIAS_NAME:-qhxd-usb-camera}"
RULE_FILE="${USB_CAMERA_RULE_FILE:-/etc/udev/rules.d/99-qhxd-usb-camera.rules}"
DEVICE="${USB_CAMERA_DEVICE:-}"

find_capture_device() {
  local dev caps bus
  for dev in /dev/video*; do
    [[ -e "${dev}" ]] || continue
    [[ "${dev}" == *video-dec* || "${dev}" == *video-enc* ]] && continue
    caps="$(udevadm info -q property -n "${dev}" 2>/dev/null | awk -F= '$1=="ID_V4L_CAPABILITIES" {print $2}')"
    bus="$(udevadm info -q property -n "${dev}" 2>/dev/null | awk -F= '$1=="ID_BUS" {print $2}')"
    if [[ "${bus}" == "usb" && "${caps}" == *capture* ]]; then
      printf '%s\n' "${dev}"
      return 0
    fi
  done
  return 1
}

if [[ -z "${DEVICE}" ]]; then
  DEVICE="$(find_capture_device || true)"
fi

if [[ -z "${DEVICE}" || ! -e "${DEVICE}" ]]; then
  echo "No USB V4L2 capture device found. Check: ls /dev/video* && v4l2-ctl --list-devices" >&2
  exit 1
fi

props="$(udevadm info -q property -n "${DEVICE}")"
vendor="$(printf '%s\n' "${props}" | awk -F= '$1=="ID_VENDOR_ID" {print $2}')"
product="$(printf '%s\n' "${props}" | awk -F= '$1=="ID_MODEL_ID" {print $2}')"
serial="$(printf '%s\n' "${props}" | awk -F= '$1=="ID_SERIAL_SHORT" {print $2}')"
caps="$(printf '%s\n' "${props}" | awk -F= '$1=="ID_V4L_CAPABILITIES" {print $2}')"

if [[ -z "${vendor}" || -z "${product}" ]]; then
  echo "Could not read USB vendor/product for ${DEVICE}" >&2
  exit 1
fi
if [[ "${caps}" != *capture* ]]; then
  echo "${DEVICE} is not a capture device: ID_V4L_CAPABILITIES=${caps}" >&2
  exit 1
fi

printf -v rule 'SUBSYSTEM=="video4linux", ATTR{index}=="0", ATTRS{idVendor}=="%s", ATTRS{idProduct}=="%s"' "${vendor}" "${product}"
if [[ -n "${serial}" ]]; then
  printf -v rule '%s, ATTRS{serial}=="%s"' "${rule}" "${serial}"
fi
printf -v rule '%s, SYMLINK+="%s", GROUP="video", MODE="0660"' "${rule}" "${ALIAS_NAME}"
echo "USB capture device: ${DEVICE}"
echo "Creating udev alias: /dev/${ALIAS_NAME}"
echo "Rule file: ${RULE_FILE}"
echo "${rule}"

printf '%s\n' "${rule}" | sudo tee "${RULE_FILE}" >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=video4linux
sleep 1

if [[ -e "/dev/${ALIAS_NAME}" ]]; then
  ls -l "/dev/${ALIAS_NAME}"
else
  echo "Alias was not created yet. Replug the USB camera or run: sudo udevadm trigger --subsystem-match=video4linux" >&2
  exit 2
fi
