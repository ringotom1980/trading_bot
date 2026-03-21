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
        entry_decision_id,
        exit_decision_id,
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
        "entry_decision_id": row[18],
        "exit_decision_id": row[19],
        "opened_at": row[20],
        "closed_at": row[21],
        "close_reason": row[22],
        "exchange_position_ref": row[23],
        "created_at": row[24],
        "updated_at": row[25],
    }

def get_position_by_id(conn: PgConnection, position_id: int) -> dict[str, Any] | None:
    """
    功能：依 position_id 查詢單筆持倉。
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
        entry_decision_id,
        exit_decision_id,
        opened_at,
        closed_at,
        close_reason,
        exchange_position_ref,
        created_at,
        updated_at
    FROM positions
    WHERE position_id = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (position_id,))
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
        "entry_decision_id": row[18],
        "exit_decision_id": row[19],
        "opened_at": row[20],
        "closed_at": row[21],
        "close_reason": row[22],
        "exchange_position_ref": row[23],
        "created_at": row[24],
        "updated_at": row[25],
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
    entry_decision_id: int | None,
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
        entry_decision_id,
        status,
        entry_price,
        entry_qty,
        entry_notional,
        fees,
        opened_at,
        exchange_position_ref
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, 'OPEN', %s, %s, %s, 0, %s, %s
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
                entry_decision_id,
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


def close_position(
    conn: PgConnection,
    *,
    position_id: int,
    exit_price: float,
    exit_qty: float,
    gross_pnl: float,
    fees: float,
    net_pnl: float,
    closed_at: datetime,
    close_reason: str,
) -> None:
    """
    功能：將指定持倉更新為 CLOSED。
    參數：
        conn: PostgreSQL 連線物件。
        position_id: 持倉主鍵。
        exit_price: 出場價格。
        exit_qty: 出場數量。
        gross_pnl: 毛損益。
        fees: 手續費。
        net_pnl: 淨損益。
        closed_at: 平倉時間。
        close_reason: 平倉原因。
    """
    sql = """
    UPDATE positions
    SET
        status = 'CLOSED',
        exit_price = %s,
        exit_qty = %s,
        gross_pnl = %s,
        fees = %s,
        net_pnl = %s,
        closed_at = %s,
        close_reason = %s,
        updated_at = NOW()
    WHERE position_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                exit_price,
                exit_qty,
                gross_pnl,
                fees,
                net_pnl,
                closed_at,
                close_reason,
                position_id,
            ),
        )


def update_position_entry_order_id(
    conn: PgConnection,
    *,
    position_id: int,
    entry_order_id: int,
) -> None:
    """
    功能：更新持倉的 entry_order_id。
    參數：
        conn: PostgreSQL 連線物件。
        position_id: 持倉主鍵。
        entry_order_id: 開倉委託單主鍵。
    """
    sql = """
    UPDATE positions
    SET
        entry_order_id = %s,
        updated_at = NOW()
    WHERE position_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (entry_order_id, position_id))


def update_position_exit_order_id(
    conn: PgConnection,
    *,
    position_id: int,
    exit_order_id: int,
) -> None:
    """
    功能：更新持倉的 exit_order_id。
    參數：
        conn: PostgreSQL 連線物件。
        position_id: 持倉主鍵。
        exit_order_id: 平倉委託單主鍵。
    """
    sql = """
    UPDATE positions
    SET
        exit_order_id = %s,
        updated_at = NOW()
    WHERE position_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (exit_order_id, position_id))


def update_position_exit_decision_id(
    conn: PgConnection,
    *,
    position_id: int,
    exit_decision_id: int,
) -> None:
    """
    功能：更新持倉的 exit_decision_id。
    參數：
        conn: PostgreSQL 連線物件。
        position_id: 持倉主鍵。
        exit_decision_id: 平倉決策主鍵。
    """
    sql = """
    UPDATE positions
    SET
        exit_decision_id = %s,
        updated_at = NOW()
    WHERE position_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (exit_decision_id, position_id))
