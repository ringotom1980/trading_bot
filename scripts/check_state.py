"""
Path: scripts/check_state.py
說明：快速檢查目前系統主狀態、ACTIVE 策略、最新 decision/order/trade/system_event，以及目前是否存在 OPEN 持倉，並顯示主要資料筆數統計。
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

from storage.db import connection_scope
from storage.repositories.decisions_repo import get_latest_decision_log
from storage.repositories.orders_repo import get_latest_order
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_id,
)
from storage.repositories.system_events_repo import (
    get_latest_system_event,
    get_system_event_count,
)
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


def _get_table_count(conn, table_name: str) -> int:
    """
    功能：查詢指定資料表總筆數。
    參數：
        conn: PostgreSQL 連線物件。
        table_name: 資料表名稱。
    回傳：
        該資料表總筆數。
    """
    sql = f"SELECT COUNT(*) FROM {table_name}"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    return int(row[0]) if row is not None else 0


def _get_open_position_count(conn) -> int:
    """
    功能：查詢目前 OPEN 持倉筆數。
    參數：
        conn: PostgreSQL 連線物件。
    回傳：
        positions.status='OPEN' 的筆數。
    """
    sql = """
    SELECT COUNT(*)
    FROM positions
    WHERE status = 'OPEN'
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    return int(row[0]) if row is not None else 0


def main() -> None:
    """
    功能：查詢並輸出目前系統狀態摘要。
    """
    with connection_scope() as conn:
        system_state = get_system_state(conn, state_id=1)
        active_strategy = get_active_strategy_version(conn)
        latest_decision = get_latest_decision_log(conn)
        latest_order = get_latest_order(conn)
        latest_trade = get_latest_trade_log(conn)
        latest_system_event = get_latest_system_event(conn)

        decision_count = _get_table_count(conn, "decisions_log")
        order_count = _get_table_count(conn, "orders")
        trade_count = _get_table_count(conn, "trades_log")
        open_position_count = _get_open_position_count(conn)
        system_event_count = get_system_event_count(conn)

        stats_summary = {
            "decision_count": decision_count,
            "order_count": order_count,
            "trade_count": trade_count,
            "open_position_count": open_position_count,
            "system_event_count": system_event_count,
        }

        open_position = None
        strategy_from_state = None

        if system_state is not None:
            primary_symbol = system_state["primary_symbol"]
            open_position = get_open_position_by_symbol(conn, primary_symbol)

            active_strategy_version_id = system_state["active_strategy_version_id"]
            if active_strategy_version_id is not None:
                strategy_from_state = get_strategy_version_by_id(
                    conn,
                    active_strategy_version_id,
                )

    print("\n==============================")
    print(" trading_bot 狀態快速檢查 ")
    print("==============================")

    _print_section("stats_summary", stats_summary)
    _print_section("system_state", system_state)
    _print_section("active_strategy (by status=ACTIVE)", active_strategy)
    _print_section("strategy_from_state (by system_state.active_strategy_version_id)", strategy_from_state)
    _print_section("open_position", open_position)
    _print_section("latest_decision", latest_decision)
    _print_section("latest_order", latest_order)
    _print_section("latest_trade", latest_trade)
    _print_section("latest_system_event", latest_system_event)

    print("\n檢查完成。")


if __name__ == "__main__":
    main()