#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${MOMENTUM_DRY_RUN_LOG_DIR:-logs}"
PID_FILE="${MOMENTUM_DRY_RUN_PID_FILE:-${LOG_DIR}/momentum_dry_run_loop.pid}"

if [[ ! -f "${PID_FILE}" ]]; then
    echo "momentum dry-run loop is not running"
    exit 0
fi

PID="$(cat "${PID_FILE}")"
if [[ -z "${PID}" ]] || ! kill -0 "${PID}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "stale pid removed"
    exit 0
fi

kill "${PID}"
echo "stopped momentum dry-run loop: pid=${PID}"

