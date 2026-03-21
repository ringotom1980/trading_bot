"""
Path: services/executors/live_executor.py
說明：LIVE 執行器，負責串接 Binance 真實下單骨架；若交易所回傳已成交，則同步建立/關閉 positions、寫入 trades_log，並更新 system_state。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from exchange.binance_client import BinanceClient
from exchange.order_executor import close_position_reduce_only, place_market_order
from storage.repositories.orders_repo import create_order, update_order_execution_result
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


def _utc_now() -> datetime:
    """
    功能：取得目前 UTC 時間。
    """
    return datetime.now(timezone.utc)


def _calculate_bars_held(entry_time: datetime, exit_time: datetime) -> int:
    """
    功能：依進出場時間計算持有幾根 15m bar。
    """
    seconds = (exit_time - entry_time).total_seconds()
    bars_held = int(seconds // (15 * 60))
    return max(bars_held, 0)


def create_live_entry_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict,
    active_strategy: dict,
    latest_kline: dict,
    decision_result: dict,
    decision_id: int,
) -> tuple[int | None, int | None, str | None, str | None]:
    """
    功能：LIVE 開倉；若已成交，直接同步建立 OPEN position。
    回傳：
        (linked_order_id, position_id_after, position_side_after, guard_reason)
    """
    client = BinanceClient(settings)
    decision = str(decision_result["decision"])
    qty = 0.01

    if decision == "ENTER_LONG":
        order_side = "BUY"
        position_side = "LONG"
    elif decision == "ENTER_SHORT":
        order_side = "SELL"
        position_side = "SHORT"
    else:
        return None, None, None, f"不支援的 LIVE 進場決策：{decision}"

    client_order_id = f"live_{decision.lower()}_{int(latest_kline['close_time'])}"

    try:
        raw_response = place_market_order(
            client,
            symbol=settings.primary_symbol,
            side=order_side,
            quantity=qty,
            reduce_only=False,
            new_client_order_id=client_order_id,
        )
    except Exception as exc:
        create_system_event(
            conn,
            event_type="ERROR",
            event_level="ERROR",
            source="SYSTEM",
            message=f"LIVE 開倉失敗：{exc}",
            details={
                "decision_id": decision_id,
                "decision": decision,
                "symbol": settings.primary_symbol,
                "qty": qty,
            },
            created_by="live_executor_entry_flow",
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
        return None, None, None, f"LIVE 開倉失敗：{exc}"

    placed_at = _utc_now()
    avg_price = float(raw_response.get("avgPrice") or latest_kline["close"])
    exchange_order_id = str(raw_response.get("orderId")) if raw_response.get("orderId") is not None else None
    exchange_status_raw = str(raw_response.get("status", "NEW"))
    filled_at = placed_at if exchange_status_raw == "FILLED" else None

    order_id = create_order(
        conn,
        position_id=None,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=str(system_state["trade_mode"]),
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        client_order_id=str(raw_response.get("clientOrderId", client_order_id)),
        exchange_order_id=exchange_order_id,
        side=order_side,
        order_type="MARKET",
        reduce_only=False,
        qty=qty,
        price=None,
        avg_price=avg_price,
        status=exchange_status_raw,
        exchange_status_raw=exchange_status_raw,
        placed_at=placed_at,
        filled_at=filled_at,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": client_order_id,
        },
        raw_response=raw_response,
    )

    update_order_execution_result(
        conn,
        order_id=order_id,
        status=exchange_status_raw,
        exchange_status_raw=exchange_status_raw,
        avg_price=avg_price,
        filled_at=filled_at,
        raw_response=raw_response,
    )

    create_system_event(
        conn,
        event_type="ENTRY_ORDER_CREATED",
        event_level="INFO",
        source="SYSTEM",
        message=f"LIVE 開倉委託已建立：{decision}",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "order_id": order_id,
            "exchange_order_id": exchange_order_id,
            "order_side": order_side,
            "position_side": position_side,
            "avg_price": avg_price,
            "qty": qty,
            "exchange_status_raw": exchange_status_raw,
        },
        created_by="live_executor_entry_flow",
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

    if exchange_status_raw != "FILLED":
        return order_id, None, position_side, None

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
        opened_at=filled_at or placed_at,
        exchange_position_ref=None,
    )

    update_position_entry_order_id(
        conn,
        position_id=position_id,
        entry_order_id=order_id,
    )

    update_current_position(
        conn,
        state_id=1,
        current_position_id=position_id,
        current_position_side=position_side,
        updated_by="live_executor_entry_flow",
    )

    create_system_event(
        conn,
        event_type="POSITION_OPENED",
        event_level="INFO",
        source="SYSTEM",
        message=f"LIVE 開倉成功：{position_side}",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "position_id": position_id,
            "order_id": order_id,
            "position_side": position_side,
            "avg_price": avg_price,
            "qty": qty,
        },
        created_by="live_executor_entry_flow",
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

    return order_id, position_id, position_side, None


def create_live_exit_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict,
    active_strategy: dict,
    latest_kline: dict,
    decision_id: int,
) -> tuple[int | None, int | None, int | None, str | None]:
    """
    功能：LIVE 平倉；若已成交，直接同步關閉 position 並寫入 trades_log。
    回傳：
        (linked_order_id, closed_position_id, trade_id, guard_reason)
    """
    open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
    if open_position is None:
        return None, None, None, "目前沒有 OPEN 持倉，無法執行 LIVE 平倉"

    client = BinanceClient(settings)
    qty = float(open_position["entry_qty"])

    if open_position["side"] == "LONG":
        order_side = "SELL"
        gross_pnl_sign = 1.0
    else:
        order_side = "BUY"
        gross_pnl_sign = -1.0

    client_order_id = f"live_exit_{int(latest_kline['close_time'])}"

    try:
        raw_response = close_position_reduce_only(
            client,
            symbol=settings.primary_symbol,
            side=order_side,
            quantity=qty,
            new_client_order_id=client_order_id,
        )
    except Exception as exc:
        create_system_event(
            conn,
            event_type="ERROR",
            event_level="ERROR",
            source="SYSTEM",
            message=f"LIVE 平倉失敗：{exc}",
            details={
                "decision_id": decision_id,
                "symbol": settings.primary_symbol,
                "position_id": int(open_position["position_id"]),
                "qty": qty,
            },
            created_by="live_executor_exit_flow",
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
        return None, None, None, f"LIVE 平倉失敗：{exc}"

    placed_at = _utc_now()
    avg_price = float(raw_response.get("avgPrice") or latest_kline["close"])
    exchange_order_id = str(raw_response.get("orderId")) if raw_response.get("orderId") is not None else None
    exchange_status_raw = str(raw_response.get("status", "NEW"))
    filled_at = placed_at if exchange_status_raw == "FILLED" else None

    order_id = create_order(
        conn,
        position_id=int(open_position["position_id"]),
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=str(system_state["trade_mode"]),
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        client_order_id=str(raw_response.get("clientOrderId", client_order_id)),
        exchange_order_id=exchange_order_id,
        side=order_side,
        order_type="MARKET",
        reduce_only=True,
        qty=qty,
        price=None,
        avg_price=avg_price,
        status=exchange_status_raw,
        exchange_status_raw=exchange_status_raw,
        placed_at=placed_at,
        filled_at=filled_at,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": True,
            "newClientOrderId": client_order_id,
        },
        raw_response=raw_response,
    )

    update_order_execution_result(
        conn,
        order_id=order_id,
        status=exchange_status_raw,
        exchange_status_raw=exchange_status_raw,
        avg_price=avg_price,
        filled_at=filled_at,
        raw_response=raw_response,
    )

    create_system_event(
        conn,
        event_type="EXIT_ORDER_CREATED",
        event_level="INFO",
        source="SYSTEM",
        message="LIVE 平倉委託已建立",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "position_id": int(open_position["position_id"]),
            "order_id": order_id,
            "exchange_order_id": exchange_order_id,
            "order_side": order_side,
            "avg_price": avg_price,
            "qty": qty,
            "exchange_status_raw": exchange_status_raw,
        },
        created_by="live_executor_exit_flow",
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

    if exchange_status_raw != "FILLED":
        return order_id, int(open_position["position_id"]), None, None

    exit_time = filled_at or placed_at
    entry_time = open_position["opened_at"]
    if exit_time <= entry_time:
        exit_time = entry_time + timedelta(microseconds=1)

    if gross_pnl_sign > 0:
        gross_pnl = (avg_price - float(open_position["entry_price"])) * qty
    else:
        gross_pnl = (float(open_position["entry_price"]) - avg_price) * qty

    fees = 0.0
    net_pnl = gross_pnl - fees
    bars_held = _calculate_bars_held(entry_time, exit_time)

    update_position_exit_order_id(
        conn,
        position_id=int(open_position["position_id"]),
        exit_order_id=order_id,
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
        closed_at=exit_time,
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
        entry_time=entry_time,
        exit_time=exit_time,
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
        exit_order_id=order_id,
    )

    update_current_position(
        conn,
        state_id=1,
        current_position_id=None,
        current_position_side=None,
        updated_by="live_executor_exit_flow",
    )

    create_system_event(
        conn,
        event_type="POSITION_CLOSED",
        event_level="INFO",
        source="SYSTEM",
        message="LIVE 平倉成功",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "position_id": int(open_position["position_id"]),
            "order_id": order_id,
            "trade_id": trade_id,
            "position_side": open_position["side"],
            "avg_price": avg_price,
            "qty": qty,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "bars_held": bars_held,
        },
        created_by="live_executor_exit_flow",
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
        message="LIVE 交易結果已寫入 trades_log",
        details={
            "decision_id": decision_id,
            "trade_id": trade_id,
            "position_id": int(open_position["position_id"]),
            "entry_order_id": open_position["entry_order_id"],
            "exit_order_id": order_id,
            "bars_held": bars_held,
            "net_pnl": net_pnl,
        },
        created_by="live_executor_exit_flow",
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

    return order_id, int(open_position["position_id"]), trade_id, None