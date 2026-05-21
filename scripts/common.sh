#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${PROJECT_ROOT}/.runtime"
LOG_DIR="${PROJECT_ROOT}/logs"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
YOLO_CONFIG="${YOLO_CONFIG:-${PROJECT_ROOT}/experiments/rknn_yolo/camera_config.json}"
BACKEND_PYTHON="${BACKEND_PYTHON:-python3}"
YOLO_PYTHON="${YOLO_PYTHON:-python3}"

mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}"

pid_file() {
  printf '%s/%s.pid\n' "${RUNTIME_DIR}" "$1"
}

log_file() {
  printf '%s/%s.log\n' "${LOG_DIR}" "$1"
}

is_running() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  local pid
  pid="$(cat "${file}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

start_service() {
  local name="$1"
  shift
  local file
  file="$(pid_file "${name}")"
  if is_running "${file}"; then
    echo "${name} already running: pid=$(cat "${file}")"
    return 0
  fi
  echo "starting ${name}..."
  "$@" >"$(log_file "${name}")" 2>&1 &
  echo "$!" >"${file}"
  sleep 1
  if is_running "${file}"; then
    echo "${name} started: pid=$(cat "${file}"), log=$(log_file "${name}")"
    return 0
  fi
  echo "${name} failed to start; last log lines:" >&2
  tail -40 "$(log_file "${name}")" >&2 || true
  return 1
}

stop_service() {
  local name="$1"
  local file
  file="$(pid_file "${name}")"
  if ! is_running "${file}"; then
    echo "${name} not running"
    rm -f "${file}"
    return 0
  fi
  local pid
  pid="$(cat "${file}")"
  echo "stopping ${name}: pid=${pid}"
  kill "${pid}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "${file}"
      echo "${name} stopped"
      return 0
    fi
    sleep 1
  done
  echo "${name} still running; sending SIGKILL"
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${file}"
}

status_service() {
  local name="$1"
  local file
  file="$(pid_file "${name}")"
  if is_running "${file}"; then
    echo "${name}: running pid=$(cat "${file}") log=$(log_file "${name}")"
  else
    echo "${name}: stopped"
  fi
}
