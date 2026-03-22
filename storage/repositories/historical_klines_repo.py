"""
Path: storage/repositories/historical_klines_repo.py
說明：historical_klines 資料表存取層，負責批次 upsert、區間查詢、最新資料查詢。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_historical_kline(row: tuple[Any, ...]) -> dict[str, Any]:
    """
    功能：將 historical_klines 查詢結果轉為字典格式。
    """
    return {
        "kline_id": row[0],
        "symbol": row[1],
        "interval": row[2],
        "market_type": row[3],
        "source": row[4],
        "open_time": row[5],
        "close_time": row[6],
        "open": float(row[7]),
        "high": float(row[8]),
        "low": float(row[9]),
        "close": float(row[10]),
        "volume": float(row[11]),
        "quote_asset_volume": float(row[12]) if row[12] is not None else None,
        "trade_count": int(row[13]) if row[13] is not None else None,
        "taker_buy_base_volume": float(row[14]) if row[14] is not None else None,
        "taker_buy_quote_volume": float(row[15]) if row[15] is not None else None,
        "created_at": row[16],
        "updated_at": row[17],
    }


def upsert_historical_klines(
    conn: PgConnection,
    *,
    rows: list[dict[str, Any]],
) -> int:
    """
    功能：批次 upsert historical_klines。
    參數：
        conn: PostgreSQL 連線物件。
        rows: K 線資料列表。
    回傳：
        實際寫入筆數（包含 insert / update）。
    """
    if not rows:
        return 0

    sql = """
    INSERT INTO historical_klines (
        symbol,
        interval,
        market_type,
        source,
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        quote_asset_volume,
        trade_count,
        taker_buy_base_volume,
        taker_buy_quote_volume,
        updated_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (symbol, interval, open_time)
    DO UPDATE SET
        market_type = EXCLUDED.market_type,
        source = EXCLUDED.source,
        close_time = EXCLUDED.close_time,
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        quote_asset_volume = EXCLUDED.quote_asset_volume,
        trade_count = EXCLUDED.trade_count,
        taker_buy_base_volume = EXCLUDED.taker_buy_base_volume,
        taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
        updated_at = NOW()
    """

    params_list: list[tuple[Any, ...]] = []
    for row in rows:
        params_list.append(
            (
                row["symbol"],
                row["interval"],
                row.get("market_type", "FUTURES"),
                row.get("source", "BINANCE"),
                row["open_time"],
                row["close_time"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
                row.get("quote_asset_volume"),
                row.get("trade_count"),
                row.get("taker_buy_base_volume"),
                row.get("taker_buy_quote_volume"),
            )
        )

    with conn.cursor() as cursor:
        cursor.executemany(sql, params_list)

    return len(rows)


def get_latest_historical_kline(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
) -> dict[str, Any] | None:
    """
    功能：查詢指定 symbol / interval 最新一根歷史 K 線。
    """
    sql = """
    SELECT
        kline_id,
        symbol,
        interval,
        market_type,
        source,
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        quote_asset_volume,
        trade_count,
        taker_buy_base_volume,
        taker_buy_quote_volume,
        created_at,
        updated_at
    FROM historical_klines
    WHERE symbol = %s
      AND interval = %s
    ORDER BY open_time DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_historical_kline(row)


def get_historical_klines_by_range(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """
    功能：查詢指定時間區間的歷史 K 線，依 open_time 正序回傳。
    """
    sql = """
    SELECT
        kline_id,
        symbol,
        interval,
        market_type,
        source,
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        quote_asset_volume,
        trade_count,
        taker_buy_base_volume,
        taker_buy_quote_volume,
        created_at,
        updated_at
    FROM historical_klines
    WHERE symbol = %s
      AND interval = %s
      AND open_time >= %s
      AND open_time < %s
    ORDER BY open_time ASC
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval, start_time, end_time))
        rows = cursor.fetchall()

    return [_row_to_historical_kline(row) for row in rows]


def get_latest_historical_klines(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    limit: int,
) -> list[dict[str, Any]]:
    """
    功能：查詢最近 N 根歷史 K 線，最終依 open_time 正序回傳。
    """
    sql = """
    SELECT
        kline_id,
        symbol,
        interval,
        market_type,
        source,
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        quote_asset_volume,
        trade_count,
        taker_buy_base_volume,
        taker_buy_quote_volume,
        created_at,
        updated_at
    FROM historical_klines
    WHERE symbol = %s
      AND interval = %s
    ORDER BY open_time DESC
    LIMIT %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval, limit))
        rows = cursor.fetchall()

    rows = list(reversed(rows))
    return [_row_to_historical_kline(row) for row in rows]