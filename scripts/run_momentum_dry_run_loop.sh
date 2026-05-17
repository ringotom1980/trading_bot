#!/usr/bin/env bash
set -euo pipefail

INTERVAL_SECONDS="${MOMENTUM_DRY_RUN_INTERVAL_SECONDS:-900}"
LOG_DIR="${MOMENTUM_DRY_RUN_LOG_DIR:-logs}"
PID_FILE="${MOMENTUM_DRY_RUN_PID_FILE:-${LOG_DIR}/momentum_dry_run_loop.pid}"

mkdir -p "${LOG_DIR}"
echo "$$" > "${PID_FILE}"

cleanup() {
    rm -f "${PID_FILE}"
}
trap cleanup EXIT

while true; do
    LOG_FILE="${LOG_DIR}/momentum_dry_run_$(date -u +%Y%m%d).log"
    {
        echo "===== $(date -u --iso-8601=seconds) ====="
        source .venv/bin/activate
        python scripts/run_momentum_testnet_cycle.py
        echo
    } >> "${LOG_FILE}" 2>&1

    sleep "${INTERVAL_SECONDS}"
done

