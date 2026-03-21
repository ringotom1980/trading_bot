"""
Path: services/executors/live_executor.py
說明：LIVE 執行器，負責串接 Binance 真實下單骨架；目前先完成真實 API 呼叫、落 orders 表與 system_events，position / trade 同步先標記為後續補完。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from exchange.binance_client import BinanceClient
from exchange.order_executor import close_position_reduce_only, place_market_order
from storage.repositories.orders_repo import create_order
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.system_events_repo import create_system_event


def _utc_now() -> datetime:
    """
    功能：取得目前 UTC 時間。
    """
    return datetime.now(timezone.utc)


def create_live_entry_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_result: dict[str, Any],
    decision_id: int,
) -> tuple[int | None, int | None, str | None, str]:
    """
    功能：LIVE 開倉骨架。
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
        filled_at=placed_at if exchange_status_raw == "FILLED" else None,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": client_order_id,
        },
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
            "note": "目前僅完成 live order 落表，position/trade 同步待下一步完成",
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

    return order_id, None, position_side, None


def create_live_exit_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_id: int,
) -> tuple[int | None, int | None, int | None, str]:
    """
    功能：LIVE 平倉骨架。
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
    else:
        order_side = "BUY"

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
        filled_at=placed_at if exchange_status_raw == "FILLED" else None,
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
            "note": "目前僅完成 live order 落表，position/trade 同步待下一步完成",
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

    return order_id, int(open_position["position_id"]), None, None