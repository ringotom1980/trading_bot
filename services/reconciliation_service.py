"""
Path: services/reconciliation_service.py
說明：啟動對帳服務，負責在 runtime loop 啟動前，讀取 Binance Futures 真實持倉與 DB OPEN position，比對後更新 system_state 並寫入 system_events。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.logging import get_logger
from config.settings import Settings
from exchange.binance_client import BinanceClient
from storage.repositories.positions_repo import get_open_position_by_symbol
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


def reconcile_startup_state(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
) -> None:
    """
    功能：啟動時比對 Binance 真實持倉與 DB OPEN position，並同步 system_state。
    說明：
        第一版僅做偵測、寫 event、同步 state，不自動修復 DB 持倉。
    """
    logger = get_logger("services.reconciliation_service")

    if settings.trade_mode not in {"TESTNET", "LIVE"}:
        logger.info("目前 trade_mode=%s，不需要執行交易所啟動對帳", settings.trade_mode)
        return

    client = BinanceClient(settings)
    db_open_position = get_open_position_by_symbol(conn, settings.primary_symbol)

    raw_positions = client.get_position_risk(symbol=settings.primary_symbol)
    exchange_side = _extract_exchange_position_side(
        list(raw_positions or []),
        settings.primary_symbol,
    )

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

    # C / D / E. 不一致，第一版先清空 state 並記異常
    update_current_position(
        conn,
        state_id=1,
        current_position_id=None,
        current_position_side=None,
        updated_by="startup_reconcile_mismatch",
    )

    create_system_event(
        conn,
        event_type="ERROR",
        event_level="ERROR",
        source="SYSTEM",
        message="啟動對帳異常：交易所持倉與 DB 持倉不一致",
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