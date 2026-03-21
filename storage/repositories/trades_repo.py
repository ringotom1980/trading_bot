"""
Path: storage/repositories/trades_repo.py
說明：交易結果資料表存取層，負責新增與查詢 trades_log。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def create_trade_log(
    conn: PgConnection,
    *,
    position_id: int,
    symbol: str,
    interval: str,
    engine_mode: str,
    trade_mode: str | None,
    strategy_version_id: int,
    side: str,
    entry_time: datetime,
    exit_time: datetime,
    entry_price: float,
    exit_price: float,
    qty: float,
    gross_pnl: float,
    fees: float,
    net_pnl: float,
    bars_held: int | None,
    close_reason: str | None,
    entry_decision_id: int | None = None,
    exit_decision_id: int | None = None,
    entry_order_id: int | None = None,
    exit_order_id: int | None = None,
    max_favorable_excursion: float | None = None,
    max_adverse_excursion: float | None = None,
) -> int:
    """
    功能：建立一筆 trades_log 資料。
    回傳：
        新建立的 trade_id。
    """
    sql = """
    INSERT INTO trades_log (
        position_id,
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        side,
        entry_time,
        exit_time,
        entry_price,
        exit_price,
        qty,
        gross_pnl,
        fees,
        net_pnl,
        bars_held,
        max_favorable_excursion,
        max_adverse_excursion,
        entry_decision_id,
        exit_decision_id,
        entry_order_id,
        exit_order_id,
        close_reason
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    RETURNING trade_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                position_id,
                symbol,
                interval,
                engine_mode,
                trade_mode,
                strategy_version_id,
                side,
                entry_time,
                exit_time,
                entry_price,
                exit_price,
                qty,
                gross_pnl,
                fees,
                net_pnl,
                bars_held,
                max_favorable_excursion,
                max_adverse_excursion,
                entry_decision_id,
                exit_decision_id,
                entry_order_id,
                exit_order_id,
                close_reason,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 trades_log 失敗：未取得 trade_id")

    return int(row[0])


def get_latest_trade_log(conn: PgConnection) -> dict[str, Any] | None:
    """
    功能：查詢最新一筆 trades_log。
    回傳：
        最新 trade 資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        trade_id,
        position_id,
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        side,
        entry_time,
        exit_time,
        entry_price,
        exit_price,
        qty,
        gross_pnl,
        fees,
        net_pnl,
        bars_held,
        max_favorable_excursion,
        max_adverse_excursion,
        entry_decision_id,
        exit_decision_id,
        entry_order_id,
        exit_order_id,
        close_reason,
        created_at
    FROM trades_log
    ORDER BY trade_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "trade_id": row[0],
        "position_id": row[1],
        "symbol": row[2],
        "interval": row[3],
        "engine_mode": row[4],
        "trade_mode": row[5],
        "strategy_version_id": row[6],
        "side": row[7],
        "entry_time": row[8],
        "exit_time": row[9],
        "entry_price": float(row[10]),
        "exit_price": float(row[11]),
        "qty": float(row[12]),
        "gross_pnl": float(row[13]),
        "fees": float(row[14]),
        "net_pnl": float(row[15]),
        "bars_held": row[16],
        "max_favorable_excursion": float(row[17]) if row[17] is not None else None,
        "max_adverse_excursion": float(row[18]) if row[18] is not None else None,
        "entry_decision_id": row[19],
        "exit_decision_id": row[20],
        "entry_order_id": row[21],
        "exit_order_id": row[22],
        "close_reason": row[23],
        "created_at": row[24],
    }
    
def get_latest_closed_trade_by_symbol(conn: PgConnection, symbol: str) -> dict[str, Any] | None:
    """
    功能：依交易標的查詢最近一筆已完成交易。
    回傳：
        最新 closed trade 資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        trade_id,
        position_id,
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        side,
        entry_time,
        exit_time,
        entry_price,
        exit_price,
        qty,
        gross_pnl,
        fees,
        net_pnl,
        bars_held,
        max_favorable_excursion,
        max_adverse_excursion,
        entry_decision_id,
        exit_decision_id,
        entry_order_id,
        exit_order_id,
        close_reason,
        created_at
    FROM trades_log
    WHERE symbol = %s
    ORDER BY trade_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol,))
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "trade_id": row[0],
        "position_id": row[1],
        "symbol": row[2],
        "interval": row[3],
        "engine_mode": row[4],
        "trade_mode": row[5],
        "strategy_version_id": row[6],
        "side": row[7],
        "entry_time": row[8],
        "exit_time": row[9],
        "entry_price": float(row[10]),
        "exit_price": float(row[11]),
        "qty": float(row[12]),
        "gross_pnl": float(row[13]),
        "fees": float(row[14]),
        "net_pnl": float(row[15]),
        "bars_held": row[16],
        "max_favorable_excursion": float(row[17]) if row[17] is not None else None,
        "max_adverse_excursion": float(row[18]) if row[18] is not None else None,
        "entry_decision_id": row[19],
        "exit_decision_id": row[20],
        "entry_order_id": row[21],
        "exit_order_id": row[22],
        "close_reason": row[23],
        "created_at": row[24],
    }