"""
Path: scripts/demo_force_trade_cycle.py
說明：強制執行模擬交易驗收流程，直接指定 ENTER_LONG、ENTER_SHORT 或 EXIT，
用來驗證 order / position / trade / system_state 是否正確更新。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.logging import setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from services.execution_service import force_simulated_trade_cycle
from services.strategy_service import load_active_strategy
from storage.db import connection_scope, test_connection
from storage.repositories.decisions_repo import get_latest_decision_log
from storage.repositories.orders_repo import get_latest_order
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.system_state_repo import get_system_state
from storage.repositories.trades_repo import get_latest_trade_log


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _print_section(title: str, data: dict[str, Any] | None) -> None:
    print(f"\n=== {title} ===")
    if data is None:
        print("None")
        return
    print(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))


def main() -> None:
    setup_logging()

    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/demo_force_trade_cycle.py ENTER_LONG|ENTER_SHORT|EXIT")

    forced_decision = sys.argv[1].strip().upper()

    ok, message = test_connection()
    if not ok:
        raise RuntimeError(message)

    print("\n==============================")
    print(" demo_force_trade_cycle 開始 ")
    print("==============================")
    print(message)
    print(f"forced_decision = {forced_decision}")

    settings = load_settings()
    client = BinanceClient(settings)

    with connection_scope() as conn:
        system_state_before = get_system_state(conn, 1)
        if system_state_before is None:
            raise RuntimeError("找不到 system_state(id=1)")

        active_strategy = load_active_strategy(conn)

        result = force_simulated_trade_cycle(
            conn,
            settings=settings,
            system_state=system_state_before,
            active_strategy=active_strategy,
            client=client,
            forced_decision=forced_decision,
        )

        system_state_after = get_system_state(conn, 1)
        open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
        latest_decision = get_latest_decision_log(conn)
        latest_order = get_latest_order(conn)
        latest_trade = get_latest_trade_log(conn)

    _print_section("result", result)
    _print_section("system_state_after", system_state_after)
    _print_section("open_position", open_position)
    _print_section("latest_decision", latest_decision)
    _print_section("latest_order", latest_order)
    _print_section("latest_trade", latest_trade)

    print("\ndemo_force_trade_cycle 完成。")


if __name__ == "__main__":
    main()