#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${MOMENTUM_DRY_RUN_LOG_DIR:-logs}"
LOG_FILE="${LOG_DIR}/momentum_dry_run_$(date -u +%Y%m%d).log"

if [[ ! -f "${LOG_FILE}" ]]; then
    echo "log file not found: ${LOG_FILE}"
    exit 0
fi

tail -n "${1:-120}" "${LOG_FILE}"

