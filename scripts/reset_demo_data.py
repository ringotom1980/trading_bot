"""
Path: scripts/reset_demo_data.py
說明：重設 demo 測試起始狀態，保留 ACTIVE 策略版本，
並將 system_state 調回可重跑 demo 的固定起點。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import connection_scope
from storage.repositories.system_state_repo import get_system_state


def reset_demo_system_state(conn) -> None:
    """
    功能：將 system_state 重設為 demo 測試固定起始值。
    """
    sql = """
    UPDATE system_state
    SET
        engine_mode = 'REALTIME',
        trade_mode = 'TESTNET',
        trading_state = 'ON',
        live_armed = FALSE,
        current_position_side = NULL,
        current_position_id = NULL,
        last_bar_close_time = NULL,
        last_decision_id = NULL,
        last_order_id = NULL,
        last_trade_id = NULL,
        updated_at = NOW(),
        updated_by = 'reset_demo_data',
        note = 'reset_demo_data 已重設 demo 起始狀態'
    WHERE id = 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)


def main() -> None:
    """
    功能：執行 demo 起始狀態重設。
    """
    with connection_scope() as conn:
        state = get_system_state(conn, state_id=1)
        if state is None:
            raise RuntimeError("找不到 system_state(id=1)，無法執行 reset_demo_data")

        reset_demo_system_state(conn)

    print("\n==============================")
    print(" reset_demo_data 完成 ")
    print("==============================")
    print("system_state 已重設為 demo 起始狀態：")
    print("- engine_mode = REALTIME")
    print("- trade_mode = TESTNET")
    print("- trading_state = ON")
    print("- live_armed = FALSE")
    print("- current_position_side = NULL")
    print("- current_position_id = NULL")
    print("- last_bar_close_time = NULL")
    print("- last_decision_id = NULL")
    print("- last_order_id = NULL")
    print("- last_trade_id = NULL")
    print("\n保留資料：")
    print("- active_strategy_version_id")
    print("- primary_symbol")
    print("- primary_interval")


if __name__ == "__main__":
    main()