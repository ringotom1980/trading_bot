#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "ERROR: python3/python not found"
    exit 1
  fi
fi

echo "== Python =="
"$PYTHON_BIN" --version

echo "== Compile =="
"$PYTHON_BIN" -m compileall -q .

echo "== Dependencies =="
"$PYTHON_BIN" - <<'PY'
import dotenv
import psycopg2
import requests
print("dependencies ok")
PY

echo "== Settings =="
"$PYTHON_BIN" - <<'PY'
from config.settings import load_settings

s = load_settings()
print(f"APP_ENV={s.app_env}")
print(f"PRIMARY_SYMBOL={s.primary_symbol}")
print(f"PRIMARY_INTERVAL={s.primary_interval}")
print(f"ENGINE_MODE={s.engine_mode}")
print(f"TRADE_MODE={s.trade_mode}")
print(f"TRADING_STATE={s.trading_state}")
print(f"LIVE_ARMED={s.live_armed}")

if s.trade_mode == "LIVE" and not s.live_armed:
    print("live guard ok: LIVE is not armed")
PY

echo "== Database =="
"$PYTHON_BIN" - <<'PY'
from storage.db import test_connection

ok, message = test_connection()
print(message)
if not ok:
    raise SystemExit(1)
PY

echo "== Binance public klines =="
"$PYTHON_BIN" - <<'PY'
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines

s = load_settings()
rows = get_latest_klines(
    BinanceClient(s),
    symbol=s.primary_symbol,
    interval=s.primary_interval,
    limit=2,
)
print(f"klines ok: count={len(rows)}, latest_close={rows[-1]['close']}")
PY

echo "healthcheck ok"
