"""
Path: storage/repositories/family_performance_summary_repo.py
說明：family_performance_summary 資料表存取層。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_family_performance_summary(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "summary_id": row[0],
        "family_key": row[1],
        "symbol": row[2],
        "interval": row[3],
        "sample_count": row[4],
        "pass_count": row[5],
        "fail_count": row[6],
        "avg_rank_score": float(row[7]),
        "avg_net_pnl": float(row[8]),
        "avg_profit_factor": float(row[9]),
        "avg_max_drawdown": float(row[10]),
        "last_run_at": row[11],
        "updated_at": row[12],
    }


def upsert_family_performance_summary(
    conn: PgConnection,
    *,
    family_key: str,
    symbol: str,
    interval: str,
    sample_count: int,
    pass_count: int,
    fail_count: int,
    avg_rank_score: float,
    avg_net_pnl: float,
    avg_profit_factor: float,
    avg_max_drawdown: float,
    last_run_at: datetime | None,
) -> int:
    sql = """
    INSERT INTO family_performance_summary (
        family_key,
        symbol,
        interval,
        sample_count,
        pass_count,
        fail_count,
        avg_rank_score,
        avg_net_pnl,
        avg_profit_factor,
        avg_max_drawdown,
        last_run_at,
        updated_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (family_key, symbol, interval)
    DO UPDATE SET
        sample_count = EXCLUDED.sample_count,
        pass_count = EXCLUDED.pass_count,
        fail_count = EXCLUDED.fail_count,
        avg_rank_score = EXCLUDED.avg_rank_score,
        avg_net_pnl = EXCLUDED.avg_net_pnl,
        avg_profit_factor = EXCLUDED.avg_profit_factor,
        avg_max_drawdown = EXCLUDED.avg_max_drawdown,
        last_run_at = EXCLUDED.last_run_at,
        updated_at = NOW()
    RETURNING summary_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                family_key,
                symbol,
                interval,
                sample_count,
                pass_count,
                fail_count,
                avg_rank_score,
                avg_net_pnl,
                avg_profit_factor,
                avg_max_drawdown,
                last_run_at,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 family_performance_summary 失敗：未取得 summary_id")

    return int(row[0])


def get_family_performance_summary(
    conn: PgConnection,
    *,
    family_key: str,
    symbol: str,
    interval: str,
) -> dict[str, Any] | None:
    sql = """
    SELECT
        summary_id,
        family_key,
        symbol,
        interval,
        sample_count,
        pass_count,
        fail_count,
        avg_rank_score,
        avg_net_pnl,
        avg_profit_factor,
        avg_max_drawdown,
        last_run_at,
        updated_at
    FROM family_performance_summary
    WHERE family_key = %s
      AND symbol = %s
      AND interval = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (family_key, symbol, interval))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_family_performance_summary(row)


def get_top_family_performance_summaries(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        summary_id,
        family_key,
        symbol,
        interval,
        sample_count,
        pass_count,
        fail_count,
        avg_rank_score,
        avg_net_pnl,
        avg_profit_factor,
        avg_max_drawdown,
        last_run_at,
        updated_at
    FROM family_performance_summary
    WHERE symbol = %s
      AND interval = %s
    ORDER BY avg_rank_score DESC, sample_count DESC, summary_id ASC
    LIMIT %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval, limit))
        rows = cursor.fetchall()

    return [_row_to_family_performance_summary(row) for row in rows]


def get_all_family_performance_summaries(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        summary_id,
        family_key,
        symbol,
        interval,
        sample_count,
        pass_count,
        fail_count,
        avg_rank_score,
        avg_net_pnl,
        avg_profit_factor,
        avg_max_drawdown,
        last_run_at,
        updated_at
    FROM family_performance_summary
    WHERE symbol = %s
      AND interval = %s
    ORDER BY avg_rank_score DESC, sample_count DESC, summary_id ASC
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval))
        rows = cursor.fetchall()

    return [_row_to_family_performance_summary(row) for row in rows]