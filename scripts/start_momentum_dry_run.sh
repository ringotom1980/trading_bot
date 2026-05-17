#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${MOMENTUM_DRY_RUN_LOG_DIR:-logs}"
PID_FILE="${MOMENTUM_DRY_RUN_PID_FILE:-${LOG_DIR}/momentum_dry_run_loop.pid}"
OUT_FILE="${LOG_DIR}/momentum_dry_run_loop.out"

mkdir -p "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
    PID="$(cat "${PID_FILE}")"
    if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
        echo "momentum dry-run loop already running: pid=${PID}"
        exit 0
    fi
    rm -f "${PID_FILE}"
fi

nohup bash scripts/run_momentum_dry_run_loop.sh > "${OUT_FILE}" 2>&1 &
echo "started momentum dry-run loop: pid=$!"

