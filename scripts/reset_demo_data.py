"""
Path: scripts/reset_demo_data.py
說明：重設 demo 測試起始狀態，保留 ACTIVE 策略版本，
並將 system_state 調回可重跑 demo 的固定起點。
可額外指定 trading_state 與 live_armed，方便驗證 guard。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import connection_scope
from storage.repositories.system_state_repo import get_system_state


ALLOWED_TRADING_STATES = {"ON", "ENTRY_FROZEN", "OFF"}


def parse_args() -> tuple[str, bool]:
    """
    功能：解析 CLI 參數。
    用法：
        python scripts/reset_demo_data.py
        python scripts/reset_demo_data.py ON
        python scripts/reset_demo_data.py ENTRY_FROZEN
        python scripts/reset_demo_data.py OFF true
    回傳：
        (trading_state, live_armed)
    """
    trading_state = "ON"
    live_armed = False

    if len(sys.argv) >= 2:
        trading_state = sys.argv[1].strip().upper()

    if len(sys.argv) >= 3:
        live_armed = sys.argv[2].strip().lower() == "true"

    if trading_state not in ALLOWED_TRADING_STATES:
        raise SystemExit(
            "用法：python scripts/reset_demo_data.py [ON|ENTRY_FROZEN|OFF] [true|false]"
        )

    return trading_state, live_armed


def reset_demo_system_state(conn, *, trading_state: str, live_armed: bool) -> None:
    """
    功能：將 system_state 重設為 demo 測試固定起始值。
    """
    sql = """
    UPDATE system_state
    SET
        engine_mode = 'REALTIME',
        trade_mode = 'TESTNET',
        trading_state = %s,
        live_armed = %s,
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
        cursor.execute(sql, (trading_state, live_armed))


def main() -> None:
    """
    功能：執行 demo 起始狀態重設。
    """
    trading_state, live_armed = parse_args()

    with connection_scope() as conn:
        state = get_system_state(conn, state_id=1)
        if state is None:
            raise RuntimeError("找不到 system_state(id=1)，無法執行 reset_demo_data")

        reset_demo_system_state(
            conn,
            trading_state=trading_state,
            live_armed=live_armed,
        )

    print("\n==============================")
    print(" reset_demo_data 完成 ")
    print("==============================")
    print("system_state 已重設為 demo 起始狀態：")
    print("- engine_mode = REALTIME")
    print("- trade_mode = TESTNET")
    print(f"- trading_state = {trading_state}")
    print(f"- live_armed = {str(live_armed).upper()}")
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