#!/usr/bin/env bash
set -euo pipefail

# QHXD uses exclusive ALSA devices for onboard recording and playback.
# Prevent the per-user PulseAudio socket from claiming those devices later.
systemctl --user mask --now pulseaudio.socket pulseaudio.service >/dev/null 2>&1 || true
pulseaudio --kill >/dev/null 2>&1 || true

PULSE_CONFIG_DIR="${HOME}/.config/pulse"
PULSE_CLIENT_CONFIG="${PULSE_CONFIG_DIR}/client.conf"
mkdir -p "${PULSE_CONFIG_DIR}"
if [[ -f "${PULSE_CLIENT_CONFIG}" ]]; then
  if grep -qE '^[[:space:]]*autospawn[[:space:]]*=' "${PULSE_CLIENT_CONFIG}"; then
    sed -i 's/^[[:space:]]*autospawn[[:space:]]*=.*/autospawn = no/' "${PULSE_CLIENT_CONFIG}"
  else
    printf '\nautospawn = no\n' >>"${PULSE_CLIENT_CONFIG}"
  fi
else
  printf 'autospawn = no\n' >"${PULSE_CLIENT_CONFIG}"
fi

echo "Robot audio mode configured: PulseAudio masked, direct ALSA enabled."
