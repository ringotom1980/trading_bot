"""
Path: scripts/reset_demo_data.py
說明：重設 demo 測試起始狀態，保留 ACTIVE 策略版本，
並將 system_state 調回可重跑 demo 的固定起點。
可額外指定 trading_state、trade_mode 與 live_armed，方便驗證 guard。
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
ALLOWED_TRADE_MODES = {"TESTNET", "LIVE"}


def parse_args() -> tuple[str, str, bool]:
    """
    功能：解析 CLI 參數。
    用法：
        python scripts/reset_demo_data.py
        python scripts/reset_demo_data.py ON
        python scripts/reset_demo_data.py ON LIVE
        python scripts/reset_demo_data.py ON LIVE false
        python scripts/reset_demo_data.py ENTRY_FROZEN TESTNET false
    回傳：
        (trading_state, trade_mode, live_armed)
    """
    trading_state = "ON"
    trade_mode = "TESTNET"
    live_armed = False

    if len(sys.argv) >= 2:
        trading_state = sys.argv[1].strip().upper()

    if len(sys.argv) >= 3:
        trade_mode = sys.argv[2].strip().upper()

    if len(sys.argv) >= 4:
        live_armed = sys.argv[3].strip().lower() == "true"

    if trading_state not in ALLOWED_TRADING_STATES:
        raise SystemExit(
            "用法：python scripts/reset_demo_data.py [ON|ENTRY_FROZEN|OFF] [TESTNET|LIVE] [true|false]"
        )

    if trade_mode not in ALLOWED_TRADE_MODES:
        raise SystemExit(
            "用法：python scripts/reset_demo_data.py [ON|ENTRY_FROZEN|OFF] [TESTNET|LIVE] [true|false]"
        )

    return trading_state, trade_mode, live_armed


def reset_demo_system_state(
    conn,
    *,
    trading_state: str,
    trade_mode: str,
    live_armed: bool,
) -> None:
    """
    功能：將 system_state 重設為 demo 測試固定起始值。
    ENTRY_FROZEN 測試時保留目前持倉參照，避免與 open_position 脫鉤。
    """
    reset_position_fields_sql = """
        current_position_side = NULL,
        current_position_id = NULL,
    """

    if trading_state == "ENTRY_FROZEN":
        reset_position_fields_sql = ""

    sql = f"""
    UPDATE system_state
    SET
        engine_mode = 'REALTIME',
        trade_mode = %s,
        trading_state = %s,
        live_armed = %s,
        {reset_position_fields_sql}
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
        cursor.execute(sql, (trade_mode, trading_state, live_armed))


def main() -> None:
    """
    功能：執行 demo 起始狀態重設。
    """
    trading_state, trade_mode, live_armed = parse_args()

    with connection_scope() as conn:
        state = get_system_state(conn, state_id=1)
        if state is None:
            raise RuntimeError("找不到 system_state(id=1)，無法執行 reset_demo_data")

        reset_demo_system_state(
            conn,
            trading_state=trading_state,
            trade_mode=trade_mode,
            live_armed=live_armed,
        )

    print("\n==============================")
    print(" reset_demo_data 完成 ")
    print("==============================")
    print("system_state 已重設為 demo 起始狀態：")
    print("- engine_mode = REALTIME")
    print(f"- trade_mode = {trade_mode}")
    print(f"- trading_state = {trading_state}")
    print(f"- live_armed = {str(live_armed).upper()}")
    if trading_state == "ENTRY_FROZEN":
        print("- current_position_side / current_position_id = 保留原值")
    else:
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