"""
Path: scripts/check_exit_guard.py
說明：檢查 exit guard，驗證 min_hold_bars / trading_state / open position 狀態。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.guards import evaluate_exit_guard
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.system_state_repo import get_system_state
from services.strategy_service import load_active_strategy


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _print_json(title: str, data: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))


def main() -> None:
    settings = load_settings()
    client = BinanceClient(settings)

    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=2,
    )
    latest_kline = klines[-1]
    current_bar_close_time = datetime.fromtimestamp(int(latest_kline["close_time"]) / 1000)

    with connection_scope() as conn:
        system_state = get_system_state(conn, state_id=1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        active_strategy = load_active_strategy(conn)
        open_position = get_open_position_by_symbol(conn, settings.primary_symbol)

    min_hold_bars = int(active_strategy["params_json"].get("min_hold_bars", 0))

    allowed, reason = evaluate_exit_guard(
        system_state,
        open_position=open_position,
        current_bar_close_time=current_bar_close_time,
        min_hold_bars=min_hold_bars,
    )

    _print_json("system_state", system_state)
    _print_json("open_position", open_position)
    _print_json(
        "exit_guard",
        {
            "allowed": allowed,
            "reason": reason,
            "min_hold_bars": min_hold_bars,
            "current_bar_close_time": current_bar_close_time,
        },
    )


if __name__ == "__main__":
    main()