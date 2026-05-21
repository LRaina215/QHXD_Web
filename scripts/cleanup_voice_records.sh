#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VOICE_DIR="${VOICE_DIR:-${PROJECT_ROOT}/backend/data/voice_records}"
DAYS="${DAYS:-7}"
MODE="${1:---dry-run}"

if [[ ! -d "${VOICE_DIR}" ]]; then
  echo "voice_records directory not found: ${VOICE_DIR}"
  exit 0
fi

if [[ "${MODE}" == "--delete" ]]; then
  echo "Deleting wav files older than ${DAYS} days from ${VOICE_DIR}"
  find "${VOICE_DIR}" -type f -name '*.wav' -mtime "+${DAYS}" -print -delete
else
  echo "Dry run: wav files older than ${DAYS} days in ${VOICE_DIR}"
  find "${VOICE_DIR}" -type f -name '*.wav' -mtime "+${DAYS}" -print
  echo "Run with --delete to remove them. Override DAYS=7 or VOICE_DIR=... if needed."
fi
