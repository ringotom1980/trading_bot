#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${MOMENTUM_DRY_RUN_LOG_DIR:-logs}"
PID_FILE="${MOMENTUM_DRY_RUN_PID_FILE:-${LOG_DIR}/momentum_dry_run_loop.pid}"

if [[ ! -f "${PID_FILE}" ]]; then
    echo "momentum dry-run loop: stopped"
    exit 0
fi

PID="$(cat "${PID_FILE}")"
if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "momentum dry-run loop: running pid=${PID}"
else
    echo "momentum dry-run loop: stale pid=${PID}"
fi

