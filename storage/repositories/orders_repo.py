"""
Path: storage/repositories/orders_repo.py
說明：委託單資料表存取層，負責新增與查詢 orders。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def create_order(
    conn: PgConnection,
    *,
    position_id: int | None,
    symbol: str,
    interval: str,
    engine_mode: str,
    trade_mode: str,
    strategy_version_id: int,
    client_order_id: str | None,
    exchange_order_id: str | None,
    side: str,
    order_type: str,
    reduce_only: bool,
    qty: float,
    price: float | None,
    avg_price: float | None,
    status: str,
    exchange_status_raw: str | None,
    placed_at: datetime,
    filled_at: datetime | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    raw_request: dict[str, Any] | None = None,
    raw_response: dict[str, Any] | None = None,
) -> int:
    """
    功能：建立一筆 orders 紀錄。
    回傳：
        新建立的 order_id。
    """
    sql = """
    INSERT INTO orders (
        position_id,
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        client_order_id,
        exchange_order_id,
        side,
        order_type,
        reduce_only,
        qty,
        price,
        avg_price,
        status,
        exchange_status_raw,
        placed_at,
        filled_at,
        error_code,
        error_message,
        raw_request_json,
        raw_response_json
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
    )
    RETURNING order_id
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
                client_order_id,
                exchange_order_id,
                side,
                order_type,
                reduce_only,
                qty,
                price,
                avg_price,
                status,
                exchange_status_raw,
                placed_at,
                filled_at,
                error_code,
                error_message,
                json.dumps(raw_request, ensure_ascii=False) if raw_request is not None else None,
                json.dumps(raw_response, ensure_ascii=False) if raw_response is not None else None,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 orders 失敗：未取得 order_id")

    return int(row[0])

def update_order_position_id(
    conn: PgConnection,
    *,
    order_id: int,
    position_id: int,
) -> None:
    """
    功能：回填 orders.position_id，讓開倉委託單可正確連回持倉。
    參數：
        conn: PostgreSQL 連線物件。
        order_id: 委託單主鍵。
        position_id: 持倉主鍵。
    """
    sql = """
    UPDATE orders
    SET
        position_id = %s,
        updated_at = NOW()
    WHERE order_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (position_id, order_id))

def get_latest_order(conn: PgConnection) -> dict[str, Any] | None:
    """
    功能：查詢最新一筆 orders。
    回傳：
        最新 order 資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        order_id,
        position_id,
        symbol,
        interval,
        engine_mode,
        trade_mode,
        strategy_version_id,
        client_order_id,
        exchange_order_id,
        side,
        order_type,
        reduce_only,
        qty,
        price,
        avg_price,
        status,
        exchange_status_raw,
        placed_at,
        updated_at,
        filled_at,
        error_code,
        error_message,
        raw_request_json,
        raw_response_json
    FROM orders
    ORDER BY order_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "order_id": row[0],
        "position_id": row[1],
        "symbol": row[2],
        "interval": row[3],
        "engine_mode": row[4],
        "trade_mode": row[5],
        "strategy_version_id": row[6],
        "client_order_id": row[7],
        "exchange_order_id": row[8],
        "side": row[9],
        "order_type": row[10],
        "reduce_only": row[11],
        "qty": float(row[12]),
        "price": float(row[13]) if row[13] is not None else None,
        "avg_price": float(row[14]) if row[14] is not None else None,
        "status": row[15],
        "exchange_status_raw": row[16],
        "placed_at": row[17],
        "updated_at": row[18],
        "filled_at": row[19],
        "error_code": row[20],
        "error_message": row[21],
        "raw_request_json": row[22],
        "raw_response_json": row[23],
    }