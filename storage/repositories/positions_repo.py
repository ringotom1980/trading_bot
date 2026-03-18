"""
Path: storage/repositories/positions_repo.py
說明：持倉資料表存取層，負責查詢與建立 positions 資料。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def get_open_position_by_symbol(conn: PgConnection, symbol: str) -> dict[str, Any] | None:
    """
    功能：依交易標的查詢目前 OPEN 持倉。
    參數：
        conn: PostgreSQL 連線物件。
        symbol: 交易標的，例如 BTCUSDT。
    回傳：
        OPEN 持倉資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        position_id,
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        side,
        status,
        entry_price,
        entry_qty,
        entry_notional,
        exit_price,
        exit_qty,
        gross_pnl,
        fees,
        net_pnl,
        entry_order_id,
        exit_order_id,
        opened_at,
        closed_at,
        close_reason,
        exchange_position_ref,
        created_at,
        updated_at
    FROM positions
    WHERE symbol = %s
      AND status = 'OPEN'
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol,))
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "position_id": row[0],
        "symbol": row[1],
        "interval": row[2],
        "engine_mode": row[3],
        "trade_mode": row[4],
        "strategy_version_id": row[5],
        "side": row[6],
        "status": row[7],
        "entry_price": float(row[8]),
        "entry_qty": float(row[9]),
        "entry_notional": float(row[10]) if row[10] is not None else None,
        "exit_price": float(row[11]) if row[11] is not None else None,
        "exit_qty": float(row[12]) if row[12] is not None else None,
        "gross_pnl": float(row[13]) if row[13] is not None else None,
        "fees": float(row[14]) if row[14] is not None else None,
        "net_pnl": float(row[15]) if row[15] is not None else None,
        "entry_order_id": row[16],
        "exit_order_id": row[17],
        "opened_at": row[18],
        "closed_at": row[19],
        "close_reason": row[20],
        "exchange_position_ref": row[21],
        "created_at": row[22],
        "updated_at": row[23],
    }


def create_position(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    engine_mode: str,
    trade_mode: str | None,
    strategy_version_id: int,
    side: str,
    entry_price: float,
    entry_qty: float,
    entry_notional: float | None,
    opened_at: datetime,
    exchange_position_ref: str | None = None,
) -> int:
    """
    功能：建立一筆新的 OPEN 持倉資料。
    回傳：
        新建立的 position_id。
    """
    sql = """
    INSERT INTO positions (
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        side,
        status,
        entry_price,
        entry_qty,
        entry_notional,
        fees,
        opened_at,
        exchange_position_ref
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, 'OPEN', %s, %s, %s, 0, %s, %s
    )
    RETURNING position_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                symbol,
                interval,
                engine_mode,
                trade_mode,
                strategy_version_id,
                side,
                entry_price,
                entry_qty,
                entry_notional,
                opened_at,
                exchange_position_ref,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 positions 失敗：未取得 position_id")

    return int(row[0])