"""
Path: scripts/run_governor_cycle.py
說明：手動執行 governor cycle。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from governor.governor import run_governor_cycle
from storage.db import connection_scope
from storage.repositories.search_space_config_repo import get_active_search_space_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run governor cycle")
    parser.add_argument("--symbol", required=True, help="交易標的，例如 BTCUSDT")
    parser.add_argument("--interval", required=True, help="週期，例如 15m")
    parser.add_argument("--run-key", default=None, help="自訂 run_key，未提供則自動產生")
    args = parser.parse_args()

    run_key = args.run_key
    if not run_key:
        run_key = (
            f"governor_{args.symbol}_{args.interval}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )

    result = run_governor_cycle(
        run_key=run_key,
        symbol=args.symbol,
        interval=args.interval,
    )

    scope_key = f"{args.symbol}:{args.interval}"
    with connection_scope() as conn:
        active_row = get_active_search_space_config(conn, scope_key=scope_key)

    payload = {
        "governor_result": result,
        "active_search_space_config_id": active_row["config_id"] if active_row else None,
        "active_search_space_config_version": active_row["config_version"] if active_row else None,
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()