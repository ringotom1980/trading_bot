"""
Path: scripts/reset_db.py
說明：清空交易流程測試資料，保留 strategy_versions 與 system_state 主資料，
並重設 system_state 的持倉/最後紀錄欄位，供後續 demo 測試重跑使用。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import connection_scope
from storage.repositories.system_state_repo import get_system_state


TRUNCATE_TABLES = [
    "trades_log",
    "orders",
    "positions",
    "decisions_log",
    "system_events",
    "job_runs",
    "heartbeat_logs",
    "validation_runs",
    "strategy_promotions",
    "evolution_candidates",
    "evolution_runs",
    "backtest_trades",
    "backtest_runs",
]


def _table_exists(conn, table_name: str) -> bool:
    """
    功能：檢查資料表是否存在。
    """
    sql = "SELECT to_regclass(%s)"
    with conn.cursor() as cursor:
        cursor.execute(sql, (table_name,))
        row = cursor.fetchone()
    return row is not None and row[0] is not None


def _truncate_existing_tables(conn) -> list[str]:
    """
    功能：清空目前資料庫中存在的測試/執行紀錄表。
    回傳：
        實際被清空的資料表名稱清單。
    """
    existing_tables: list[str] = []

    for table_name in TRUNCATE_TABLES:
        if _table_exists(conn, table_name):
            existing_tables.append(table_name)

    if not existing_tables:
        return existing_tables

    sql = "TRUNCATE TABLE " + ", ".join(existing_tables) + " RESTART IDENTITY CASCADE"
    with conn.cursor() as cursor:
        cursor.execute(sql)

    return existing_tables


def _reset_system_state(conn) -> None:
    """
    功能：重設 system_state 的交易執行痕跡欄位，但保留主設定資料。
    """
    sql = """
    UPDATE system_state
    SET
        current_position_side = NULL,
        current_position_id = NULL,
        last_bar_close_time = NULL,
        last_decision_id = NULL,
        last_order_id = NULL,
        last_trade_id = NULL,
        updated_at = NOW(),
        updated_by = 'reset_db',
        note = 'reset_db 已清空測試資料'
    WHERE id = 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)


def main() -> None:
    """
    功能：執行測試資料清空與主狀態重設。
    """
    with connection_scope() as conn:
        state = get_system_state(conn, state_id=1)
        if state is None:
            raise RuntimeError("找不到 system_state(id=1)，無法執行 reset_db")

        truncated_tables = _truncate_existing_tables(conn)
        _reset_system_state(conn)

    print("\n==============================")
    print(" reset_db 完成 ")
    print("==============================")
    print("已清空資料表：")
    if truncated_tables:
        for table_name in truncated_tables:
            print(f"- {table_name}")
    else:
        print("- 無可清空資料表")

    print("\nsystem_state 已重設以下欄位：")
    print("- current_position_side = NULL")
    print("- current_position_id = NULL")
    print("- last_bar_close_time = NULL")
    print("- last_decision_id = NULL")
    print("- last_order_id = NULL")
    print("- last_trade_id = NULL")
    print("\n保留資料：")
    print("- strategy_versions")
    print("- system_state 主設定欄位")


if __name__ == "__main__":
    main()