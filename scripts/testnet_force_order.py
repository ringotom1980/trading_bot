"""
Path: scripts/testnet_force_order.py
說明：強制執行 Binance Demo/Testnet 真實下單驗證流程。
可指定 ENTER_LONG、ENTER_SHORT、EXIT，直接走 live/testnet executor，
用來驗證 Binance Demo 下單、orders、positions、trades_log、system_state 是否正確同步。
"""

from __future__ import annotations
from storage.repositories.trades_repo import get_latest_trade_log
from storage.repositories.system_state_repo import get_system_state, update_runtime_refs
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.orders_repo import get_latest_order
from storage.repositories.decisions_repo import (
    get_decision_by_bar_close_time,
    insert_decision_log,
    mark_decision_executed,
)
from storage.db import connection_scope, test_connection
from services.strategy_service import load_active_strategy
from services.executors.live_executor import (
    create_live_entry_flow,
    create_live_exit_flow,
)
from exchange.market_data import get_latest_klines
from exchange.binance_client import BinanceClient
from config.settings import load_settings
from config.logging import setup_logging

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


def _get_safe_bar_times(
    conn,
    *,
    symbol: str,
    interval: str,
    latest_kline: dict[str, Any],
) -> tuple[datetime, datetime]:
    """
    功能：避免 testnet_force_order 寫入重複的 bar_close_time。
    若同一根 bar 已有 decision，則自動加 1 微秒避開唯一鍵。
    """
    base_open_time = datetime.fromtimestamp(
        int(latest_kline["open_time"]) / 1000)
    base_close_time = datetime.fromtimestamp(
        int(latest_kline["close_time"]) / 1000)

    existing = get_decision_by_bar_close_time(
        conn,
        symbol=symbol,
        interval=interval,
        bar_close_time=base_close_time,
    )

    if existing is None:
        return base_open_time, base_close_time

    return (
        base_open_time.replace(microsecond=base_open_time.microsecond + 1),
        base_close_time.replace(microsecond=base_close_time.microsecond + 1),
    )


def main() -> None:
    setup_logging()

    if len(sys.argv) != 2:
        raise SystemExit(
            "用法：python scripts/testnet_force_order.py ENTER_LONG|ENTER_SHORT|EXIT")

    forced_decision = sys.argv[1].strip().upper()
    allowed = {"ENTER_LONG", "ENTER_SHORT", "EXIT"}
    if forced_decision not in allowed:
        raise SystemExit("forced_decision 僅允許 ENTER_LONG|ENTER_SHORT|EXIT")

    ok, message = test_connection()
    if not ok:
        raise RuntimeError(message)

    print("\n==============================")
    print(" testnet_force_order 開始 ")
    print("==============================")
    print(message)
    print(f"forced_decision = {forced_decision}")

    settings = load_settings()
    client = BinanceClient(settings)

    with connection_scope() as conn:
        system_state_before = get_system_state(conn, 1)
        if system_state_before is None:
            raise RuntimeError("找不到 system_state(id=1)")

        if str(system_state_before["trade_mode"]) != "TESTNET":
            raise RuntimeError(
                "目前 system_state.trade_mode 不是 TESTNET，不能執行 testnet_force_order")

        if str(system_state_before["engine_mode"]) != "REALTIME":
            raise RuntimeError(
                "目前 system_state.engine_mode 不是 REALTIME，不能執行 testnet_force_order")

        if str(system_state_before["trading_state"]) != "ON":
            raise RuntimeError(
                "目前 system_state.trading_state 不是 ON，請先 reset_demo_data.py ON TESTNET false")

        active_strategy = load_active_strategy(conn)
        klines = get_latest_klines(
            client=client,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            limit=60,
        )
        latest_kline = klines[-1]

        target_bar_open_time, target_bar_close_time = _get_safe_bar_times(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            latest_kline=latest_kline,
        )

        decision_id = insert_decision_log(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            bar_open_time=target_bar_open_time,
            bar_close_time=target_bar_close_time,
            engine_mode=system_state_before["engine_mode"],
            trade_mode=system_state_before["trade_mode"],
            strategy_version_id=int(active_strategy["strategy_version_id"]),
            position_id_before=system_state_before["current_position_id"],
            position_side_before=system_state_before["current_position_side"],
            decision=forced_decision,
            decision_score=1.0,
            reason_code="MANUAL",
            reason_summary=f"testnet force {forced_decision.lower()}",
            features={"source": "testnet_force_order"},
            executed=False,
            position_id_after=None,
            position_side_after=system_state_before["current_position_side"],
            linked_order_id=None,
        )

        linked_order_id = None
        position_id_after = system_state_before["current_position_id"]
        position_side_after = system_state_before["current_position_side"]
        last_trade_id = None
        guard_reason = None
        executed = False

        if forced_decision in {"ENTER_LONG", "ENTER_SHORT"}:
            if system_state_before["current_position_id"] is not None:
                raise RuntimeError("目前已有 OPEN 持倉，不能再強制進場")

            linked_order_id, position_id_after, position_side_after, guard_reason = create_live_entry_flow(
                conn,
                settings=settings,
                system_state=system_state_before,
                active_strategy=active_strategy,
                latest_kline=latest_kline,
                decision_result={"decision": forced_decision},
                decision_id=decision_id,
            )
            executed = linked_order_id is not None

        elif forced_decision == "EXIT":
            if system_state_before["current_position_id"] is None:
                raise RuntimeError("目前沒有 OPEN 持倉，不能強制平倉")

            linked_order_id, _closed_position_id, last_trade_id, guard_reason = create_live_exit_flow(
                conn,
                settings=settings,
                system_state=system_state_before,
                active_strategy=active_strategy,
                latest_kline=latest_kline,
                decision_id=decision_id,
            )
            executed = linked_order_id is not None
            if last_trade_id is not None:
                position_id_after = None
                position_side_after = None

        mark_decision_executed(
            conn,
            decision_id=decision_id,
            executed=executed,
            position_id_after=position_id_after,
            position_side_after=position_side_after,
            linked_order_id=linked_order_id,
        )

        update_runtime_refs(
            conn,
            state_id=1,
            last_bar_close_time=target_bar_close_time,
            last_decision_id=decision_id,
            last_order_id=linked_order_id,
            last_trade_id=last_trade_id,
            updated_by="testnet_force_order",
        )

        system_state_after = get_system_state(conn, 1)
        open_position = get_open_position_by_symbol(
            conn, settings.primary_symbol)
        latest_order = get_latest_order(conn)
        latest_trade = get_latest_trade_log(conn)

    _print_section("result", {
        "decision_id": decision_id,
        "decision": forced_decision,
        "executed": executed,
        "linked_order_id": linked_order_id,
        "position_id_after": position_id_after,
        "position_side_after": position_side_after,
        "last_trade_id": last_trade_id,
        "guard_reason": guard_reason,
    })
    _print_section("system_state_after", system_state_after)
    _print_section("open_position", open_position)
    _print_section("latest_order", latest_order)
    _print_section("latest_trade", latest_trade)

    print("\ntestnet_force_order 完成。")


if __name__ == "__main__":
    main()
