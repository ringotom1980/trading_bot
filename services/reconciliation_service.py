"""
Path: services/reconciliation_service.py
說明：啟動對帳服務，負責在 runtime loop 啟動前，讀取 Binance Futures 真實持倉與 DB OPEN position，比對後更新 system_state 並寫入 system_events。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.logging import get_logger
from config.settings import Settings
from exchange.binance_client import BinanceClient
from storage.repositories.positions_repo import (
    create_position,
    get_open_position_by_exchange_ref,
    get_open_position_by_symbol,
)
from storage.repositories.system_events_repo import create_system_event
from storage.repositories.system_state_repo import update_current_position


def _extract_exchange_position_side(position_rows: list[dict[str, Any]], symbol: str) -> str | None:
    """
    功能：從 Binance positionRisk 回傳中，解析指定 symbol 的持倉方向。
    回傳：
        LONG / SHORT / None
    """
    for row in position_rows:
        if str(row.get("symbol")) != symbol:
            continue

        position_amt = float(row.get("positionAmt") or 0.0)
        if position_amt > 0:
            return "LONG"
        if position_amt < 0:
            return "SHORT"

    return None


def _get_exchange_position_row(
    position_rows: list[dict[str, Any]],
    symbol: str,
) -> dict[str, Any] | None:
    """
    功能：取得指定 symbol 的 Binance positionRisk 原始持倉列。
    """
    for row in position_rows:
        if str(row.get("symbol")) != symbol:
            continue

        position_amt = float(row.get("positionAmt") or 0.0)
        if position_amt != 0:
            return row

    return None


def _build_exchange_position_ref(symbol: str, side: str, qty: float) -> str:
    """
    功能：建立啟動接管用的 exchange_position_ref。
    """
    return f"startup_adopt:{symbol}:{side}:{qty:.8f}"


def reconcile_startup_state(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
) -> None:
    """
    功能：啟動時比對 Binance 真實持倉與 DB OPEN position，並同步 system_state。
    說明：
        - 若交易所有倉、DB 無倉：自動接管為 DB OPEN position。
        - 若 DB 有倉、交易所無倉：視為異常，停止啟動。
        - 若雙方都有倉但方向不一致：視為異常，停止啟動。
    """
    logger = get_logger("services.reconciliation_service")

    if settings.trade_mode not in {"TESTNET", "LIVE"}:
        logger.info("目前 trade_mode=%s，不需要執行交易所啟動對帳", settings.trade_mode)
        return

    client = BinanceClient(settings)
    db_open_position = get_open_position_by_symbol(conn, settings.primary_symbol)

    raw_positions = list(client.get_position_risk(symbol=settings.primary_symbol) or [])
    exchange_row = _get_exchange_position_row(raw_positions, settings.primary_symbol)
    exchange_side = _extract_exchange_position_side(raw_positions, settings.primary_symbol)

    db_side = db_open_position["side"] if db_open_position is not None else None
    db_position_id = int(db_open_position["position_id"]) if db_open_position is not None else None

    logger.info(
        "啟動對帳結果：symbol=%s, exchange_side=%s, db_side=%s, db_position_id=%s",
        settings.primary_symbol,
        exchange_side,
        db_side,
        db_position_id,
    )

    # A. 交易所無持倉，DB 無 OPEN position
    if exchange_side is None and db_open_position is None:
        update_current_position(
            conn,
            state_id=1,
            current_position_id=None,
            current_position_side=None,
            updated_by="startup_reconcile_no_position",
        )
        create_system_event(
            conn,
            event_type="MANUAL_ACTION",
            event_level="INFO",
            source="SYSTEM",
            message="啟動對帳完成：交易所與 DB 皆無持倉",
            details={
                "symbol": settings.primary_symbol,
                "exchange_side": None,
                "db_side": None,
                "db_position_id": None,
            },
            created_by="reconcile_startup_state",
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
        return

    # B. 交易所與 DB 都有持倉，且方向一致
    if exchange_side is not None and db_open_position is not None and exchange_side == db_side:
        update_current_position(
            conn,
            state_id=1,
            current_position_id=db_position_id,
            current_position_side=db_side,
            updated_by="startup_reconcile_matched_position",
        )
        create_system_event(
            conn,
            event_type="MANUAL_ACTION",
            event_level="INFO",
            source="SYSTEM",
            message="啟動對帳完成：交易所與 DB 持倉一致",
            details={
                "symbol": settings.primary_symbol,
                "exchange_side": exchange_side,
                "db_side": db_side,
                "db_position_id": db_position_id,
            },
            created_by="reconcile_startup_state",
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
        return

    # C. 交易所有倉，DB 無倉 -> 自動接管
    if exchange_side is not None and db_open_position is None:
        if exchange_row is None:
            raise RuntimeError("啟動對帳異常：exchange_side 存在，但找不到 exchange position row")

        position_amt = abs(float(exchange_row.get("positionAmt") or 0.0))
        entry_price = float(exchange_row.get("entryPrice") or 0.0)

        if position_amt <= 0 or entry_price <= 0:
            raise RuntimeError(
                f"啟動對帳異常：無法接管交易所持倉，position_amt={position_amt}, entry_price={entry_price}"
            )

        exchange_position_ref = _build_exchange_position_ref(
            settings.primary_symbol,
            exchange_side,
            position_amt,
        )

        existing_adopted = get_open_position_by_exchange_ref(conn, exchange_position_ref)

        if existing_adopted is not None:
            adopted_position_id = int(existing_adopted["position_id"])
        else:
            adopted_position_id = create_position(
                conn,
                symbol=settings.primary_symbol,
                interval=settings.primary_interval,
                engine_mode=system_state["engine_mode"],
                trade_mode=system_state["trade_mode"],
                strategy_version_id=int(system_state["active_strategy_version_id"]),
                side=exchange_side,
                entry_decision_id=None,
                entry_price=entry_price,
                entry_qty=position_amt,
                entry_notional=entry_price * position_amt,
                opened_at=datetime.now(timezone.utc),
                exchange_position_ref=exchange_position_ref,
            )

        update_current_position(
            conn,
            state_id=1,
            current_position_id=adopted_position_id,
            current_position_side=exchange_side,
            updated_by="startup_reconcile_adopt_exchange_position",
        )

        create_system_event(
            conn,
            event_type="MANUAL_ACTION",
            event_level="INFO",
            source="SYSTEM",
            message="啟動對帳接管成功：交易所有倉、DB 無倉，已建立接管持倉",
            details={
                "symbol": settings.primary_symbol,
                "exchange_side": exchange_side,
                "db_side": None,
                "adopted_position_id": adopted_position_id,
                "entry_price": entry_price,
                "entry_qty": position_amt,
                "exchange_position_ref": exchange_position_ref,
            },
            created_by="reconcile_startup_state",
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
        return

    # D. 交易所無倉，DB 有倉 -> 危險，停機
    if exchange_side is None and db_open_position is not None:
        update_current_position(
            conn,
            state_id=1,
            current_position_id=None,
            current_position_side=None,
            updated_by="startup_reconcile_exchange_empty_db_open",
        )

        create_system_event(
            conn,
            event_type="ERROR",
            event_level="ERROR",
            source="SYSTEM",
            message="啟動對帳異常：交易所無倉，但 DB 仍有 OPEN 持倉",
            details={
                "symbol": settings.primary_symbol,
                "exchange_side": None,
                "db_side": db_side,
                "db_position_id": db_position_id,
            },
            created_by="reconcile_startup_state",
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
        raise RuntimeError("啟動對帳失敗：交易所無倉，但 DB 仍有 OPEN 持倉")

    # E. 雙方都有倉，但方向不一致 -> 危險，停機
    create_system_event(
        conn,
        event_type="ERROR",
        event_level="ERROR",
        source="SYSTEM",
        message="啟動對帳異常：交易所持倉與 DB 持倉方向不一致",
        details={
            "symbol": settings.primary_symbol,
            "exchange_side": exchange_side,
            "db_side": db_side,
            "db_position_id": db_position_id,
        },
        created_by="reconcile_startup_state",
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
    raise RuntimeError("啟動對帳失敗：交易所持倉與 DB 持倉方向不一致")