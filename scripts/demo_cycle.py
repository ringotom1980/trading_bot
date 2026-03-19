"""
Path: scripts/demo_cycle.py
說明：執行一次 demo 驗收流程，包含檢查資料庫、載入 system_state 與 ACTIVE 策略、
執行一次 runtime，最後輸出最新 system_state / decision / order / trade / open_position 摘要。
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
from core.runtime import run_runtime_once
from services.strategy_service import load_active_strategy
from storage.db import connection_scope, test_connection
from storage.repositories.decisions_repo import get_latest_decision_log
from storage.repositories.orders_repo import get_latest_order
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.system_state_repo import get_system_state
from storage.repositories.trades_repo import get_latest_trade_log


def _json_default(value: Any) -> str:
    """
    功能：提供 json.dumps 無法直接序列化物件的轉字串處理。
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _print_section(title: str, data: dict[str, Any] | None) -> None:
    """
    功能：格式化輸出單一區塊資料。
    """
    print(f"\n=== {title} ===")
    if data is None:
        print("None")
        return

    print(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))


def main() -> None:
    """
    功能：執行一次完整 demo cycle。
    """
    setup_logging()

    ok, message = test_connection()
    if not ok:
        raise RuntimeError(message)

    print("\n==============================")
    print(" demo_cycle 開始 ")
    print("==============================")
    print(message)

    settings = load_settings()

    with connection_scope() as conn:
        system_state_before = get_system_state(conn, 1)
        if system_state_before is None:
            raise RuntimeError("找不到 system_state(id=1)，無法執行 demo_cycle")

        active_strategy = load_active_strategy(conn)

        print("\n執行前狀態：")
        print(f"- state_id = {system_state_before['id']}")
        print(f"- engine_mode = {system_state_before['engine_mode']}")
        print(f"- trade_mode = {system_state_before['trade_mode']}")
        print(f"- trading_state = {system_state_before['trading_state']}")
        print(f"- current_position_id = {system_state_before['current_position_id']}")
        print(f"- current_position_side = {system_state_before['current_position_side']}")
        print(f"- active_strategy_version_id = {system_state_before['active_strategy_version_id']}")
        print(f"- active_version_code = {active_strategy['version_code']}")

        run_runtime_once(
            conn,
            settings=settings,
            active_strategy=active_strategy,
        )

        system_state_after = get_system_state(conn, 1)
        latest_decision = get_latest_decision_log(conn)
        latest_order = get_latest_order(conn)
        latest_trade = get_latest_trade_log(conn)

        open_position = None
        if system_state_after is not None:
            open_position = get_open_position_by_symbol(
                conn,
                system_state_after["primary_symbol"],
            )

    print("\n==============================")
    print(" demo_cycle 結果 ")
    print("==============================")

    _print_section("system_state_after", system_state_after)
    _print_section("open_position", open_position)
    _print_section("latest_decision", latest_decision)
    _print_section("latest_order", latest_order)
    _print_section("latest_trade", latest_trade)

    print("\ndemo_cycle 完成。")


if __name__ == "__main__":
    main()