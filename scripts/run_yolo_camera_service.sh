#!/usr/bin/env bash
set -euo pipefail

RESTART_DELAY="${YOLO_RESTART_DELAY:-3}"
child_pid=""

# Keep YOLO/RKNN on the system Python package set. Interactive shells may
# carry FunASR virtualenv PYTHONPATH values that break OpenCV's NumPy ABI.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV CONDA_PREFIX CONDA_DEFAULT_ENV

stop_child() {
  if [[ -n "${child_pid}" ]] && kill -0 "${child_pid}" 2>/dev/null; then
    kill "${child_pid}" 2>/dev/null || true
    wait "${child_pid}" 2>/dev/null || true
  fi
}

trap 'stop_child; exit 0' INT TERM

while true; do
  "$@" &
  child_pid="$!"
  set +e
  wait "${child_pid}"
  exit_code="$?"
  set -e
  child_pid=""

  if [[ "${exit_code}" -eq 0 ]]; then
    exit 0
  fi

  echo "YOLO camera worker exited with code ${exit_code}; restarting in ${RESTART_DELAY}s." >&2
  sleep "${RESTART_DELAY}"
done
