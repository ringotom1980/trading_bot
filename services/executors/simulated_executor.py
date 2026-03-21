"""
Path: services/executors/simulated_executor.py
說明：模擬執行器，負責 TESTNET / demo 階段的模擬開倉與模擬平倉流程，集中處理 order / position / trade / system_state / system_events 寫入。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from storage.repositories.orders_repo import create_order, update_order_position_id
from storage.repositories.positions_repo import (
    close_position,
    create_position,
    get_open_position_by_symbol,
    update_position_entry_order_id,
    update_position_exit_decision_id,
    update_position_exit_order_id,
)
from storage.repositories.system_events_repo import create_system_event
from storage.repositories.system_state_repo import update_current_position
from storage.repositories.trades_repo import create_trade_log


def _ms_to_datetime(ms: int) -> datetime:
    """
    功能：將毫秒時間戳轉為 UTC datetime。
    """
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _calculate_bars_held(entry_time: datetime, exit_time: datetime) -> int:
    """
    功能：依進出場時間計算持有幾根 15m bar。
    """
    seconds = (exit_time - entry_time).total_seconds()
    bars_held = int(seconds // (15 * 60))
    return max(bars_held, 0)


def create_simulated_entry_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_result: dict[str, Any],
    decision_id: int,
) -> tuple[int, int, str]:
    """
    功能：依 ENTER_LONG / ENTER_SHORT 建立模擬開倉 order 與 position。
    回傳：
        (order_id, position_id, position_side)
    """
    decision = str(decision_result["decision"])
    avg_price = float(latest_kline["close"])
    qty = 0.01
    placed_at = _ms_to_datetime(int(latest_kline["close_time"]))

    if decision == "ENTER_LONG":
        order_side = "BUY"
        position_side = "LONG"
    elif decision == "ENTER_SHORT":
        order_side = "SELL"
        position_side = "SHORT"
    else:
        raise ValueError(f"不支援的進場決策：{decision}")

    order_id = create_order(
        conn,
        position_id=None,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=str(system_state["trade_mode"]),
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        client_order_id=f"runtime_{decision.lower()}_{int(latest_kline['close_time'])}",
        exchange_order_id=f"sim_{decision.lower()}_{int(latest_kline['close_time'])}",
        side=order_side,
        order_type="MARKET",
        reduce_only=False,
        qty=qty,
        price=None,
        avg_price=avg_price,
        status="FILLED",
        exchange_status_raw="FILLED",
        placed_at=placed_at,
        filled_at=placed_at,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
        },
        raw_response={
            "status": "FILLED",
            "avgPrice": str(avg_price),
        },
    )

    create_system_event(
        conn,
        event_type="ENTRY_ORDER_CREATED",
        event_level="INFO",
        source="SYSTEM",
        message=f"模擬開倉委託已建立：{decision}",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "order_id": order_id,
            "order_side": order_side,
            "position_side": position_side,
            "avg_price": avg_price,
            "qty": qty,
        },
        created_by="simulated_executor_entry_flow",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    entry_notional = avg_price * qty

    position_id = create_position(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=system_state["trade_mode"],
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        side=position_side,
        entry_decision_id=decision_id,
        entry_price=avg_price,
        entry_qty=qty,
        entry_notional=entry_notional,
        opened_at=placed_at,
        exchange_position_ref=None,
    )

    update_position_entry_order_id(
        conn,
        position_id=position_id,
        entry_order_id=order_id,
    )

    update_order_position_id(
        conn,
        order_id=order_id,
        position_id=position_id,
    )

    update_current_position(
        conn,
        state_id=1,
        current_position_id=position_id,
        current_position_side=position_side,
        updated_by="simulated_executor_entry_flow",
    )

    create_system_event(
        conn,
        event_type="POSITION_OPENED",
        event_level="INFO",
        source="SYSTEM",
        message=f"模擬開倉成功：{position_side}",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "position_id": position_id,
            "order_id": order_id,
            "position_side": position_side,
            "avg_price": avg_price,
            "qty": qty,
            "decision": decision,
        },
        created_by="simulated_executor_entry_flow",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    return order_id, position_id, position_side


def create_simulated_exit_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_id: int,
) -> tuple[int, int, int]:
    """
    功能：依目前 OPEN 持倉建立模擬平倉 order、關閉 position 並寫入 trades_log。
    回傳：
        (exit_order_id, closed_position_id, trade_id)
    """
    open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
    if open_position is None:
        raise RuntimeError("目前沒有 OPEN 持倉，無法執行模擬平倉流程")

    avg_price = float(latest_kline["close"])
    qty = float(open_position["entry_qty"])
    filled_at = _ms_to_datetime(int(latest_kline["close_time"]))

    opened_at = open_position["opened_at"]
    if filled_at <= opened_at:
        filled_at = opened_at + timedelta(microseconds=1)

    if open_position["side"] == "LONG":
        order_side = "SELL"
        gross_pnl = (avg_price - float(open_position["entry_price"])) * qty
    else:
        order_side = "BUY"
        gross_pnl = (float(open_position["entry_price"]) - avg_price) * qty

    fees = 2.0
    net_pnl = gross_pnl - fees
    bars_held = _calculate_bars_held(opened_at, filled_at)

    exit_order_id = create_order(
        conn,
        position_id=int(open_position["position_id"]),
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=str(system_state["trade_mode"]),
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        client_order_id=f"runtime_exit_{int(latest_kline['close_time'])}",
        exchange_order_id=f"sim_exit_{int(latest_kline['close_time'])}",
        side=order_side,
        order_type="MARKET",
        reduce_only=True,
        qty=qty,
        price=None,
        avg_price=avg_price,
        status="FILLED",
        exchange_status_raw="FILLED",
        placed_at=filled_at,
        filled_at=filled_at,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": True,
        },
        raw_response={
            "status": "FILLED",
            "avgPrice": str(avg_price),
        },
    )

    create_system_event(
        conn,
        event_type="EXIT_ORDER_CREATED",
        event_level="INFO",
        source="SYSTEM",
        message="模擬平倉委託已建立",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "position_id": int(open_position["position_id"]),
            "order_id": exit_order_id,
            "order_side": order_side,
            "avg_price": avg_price,
            "qty": qty,
        },
        created_by="simulated_executor_exit_flow",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    update_position_exit_order_id(
        conn,
        position_id=int(open_position["position_id"]),
        exit_order_id=exit_order_id,
    )

    update_position_exit_decision_id(
        conn,
        position_id=int(open_position["position_id"]),
        exit_decision_id=decision_id,
    )

    close_position(
        conn,
        position_id=int(open_position["position_id"]),
        exit_price=avg_price,
        exit_qty=qty,
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        closed_at=filled_at,
        close_reason="SIGNAL_EXIT",
    )

    trade_id = create_trade_log(
        conn,
        position_id=int(open_position["position_id"]),
        symbol=str(open_position["symbol"]),
        interval=str(open_position["interval"]),
        engine_mode=str(open_position["engine_mode"]),
        trade_mode=open_position["trade_mode"],
        strategy_version_id=int(open_position["strategy_version_id"]),
        side=str(open_position["side"]),
        entry_time=open_position["opened_at"],
        exit_time=filled_at,
        entry_price=float(open_position["entry_price"]),
        exit_price=avg_price,
        qty=qty,
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        bars_held=bars_held,
        close_reason="SIGNAL_EXIT",
        entry_decision_id=open_position["entry_decision_id"],
        exit_decision_id=decision_id,
        entry_order_id=open_position["entry_order_id"],
        exit_order_id=exit_order_id,
    )

    update_current_position(
        conn,
        state_id=1,
        current_position_id=None,
        current_position_side=None,
        updated_by="simulated_executor_exit_flow",
    )

    create_system_event(
        conn,
        event_type="POSITION_CLOSED",
        event_level="INFO",
        source="SYSTEM",
        message="模擬平倉成功",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "position_id": int(open_position["position_id"]),
            "order_id": exit_order_id,
            "trade_id": trade_id,
            "position_side": open_position["side"],
            "avg_price": avg_price,
            "qty": qty,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "bars_held": bars_held,
        },
        created_by="simulated_executor_exit_flow",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    create_system_event(
        conn,
        event_type="TRADE_RECORDED",
        event_level="INFO",
        source="SYSTEM",
        message="交易結果已寫入 trades_log",
        details={
            "decision_id": decision_id,
            "trade_id": trade_id,
            "position_id": int(open_position["position_id"]),
            "entry_order_id": open_position["entry_order_id"],
            "exit_order_id": exit_order_id,
            "bars_held": bars_held,
            "net_pnl": net_pnl,
        },
        created_by="simulated_executor_exit_flow",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    return exit_order_id, int(open_position["position_id"]), trade_id