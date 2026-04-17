"""
Path: storage/repositories/feature_diagnostics_summary_repo.py
說明：feature_diagnostics_summary 資料表存取層。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_feature_diagnostics_summary(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "summary_id": row[0],
        "feature_key": row[1],
        "symbol": row[2],
        "interval": row[3],
        "winner_avg": float(row[4]),
        "loser_avg": float(row[5]),
        "winner_count": row[6],
        "loser_count": row[7],
        "diagnostic_score": float(row[8]),
        "updated_at": row[9],
    }


def upsert_feature_diagnostics_summary(
    conn: PgConnection,
    *,
    feature_key: str,
    symbol: str,
    interval: str,
    winner_avg: float,
    loser_avg: float,
    winner_count: int,
    loser_count: int,
    diagnostic_score: float,
) -> int:
    sql = """
    INSERT INTO feature_diagnostics_summary (
        feature_key,
        symbol,
        interval,
        winner_avg,
        loser_avg,
        winner_count,
        loser_count,
        diagnostic_score,
        updated_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (feature_key, symbol, interval)
    DO UPDATE SET
        winner_avg = EXCLUDED.winner_avg,
        loser_avg = EXCLUDED.loser_avg,
        winner_count = EXCLUDED.winner_count,
        loser_count = EXCLUDED.loser_count,
        diagnostic_score = EXCLUDED.diagnostic_score,
        updated_at = NOW()
    RETURNING summary_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                feature_key,
                symbol,
                interval,
                winner_avg,
                loser_avg,
                winner_count,
                loser_count,
                diagnostic_score,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 feature_diagnostics_summary 失敗：未取得 summary_id")

    return int(row[0])


def get_feature_diagnostics_summary(
    conn: PgConnection,
    *,
    feature_key: str,
    symbol: str,
    interval: str,
) -> dict[str, Any] | None:
    sql = """
    SELECT
        summary_id,
        feature_key,
        symbol,
        interval,
        winner_avg,
        loser_avg,
        winner_count,
        loser_count,
        diagnostic_score,
        updated_at
    FROM feature_diagnostics_summary
    WHERE feature_key = %s
      AND symbol = %s
      AND interval = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (feature_key, symbol, interval))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_feature_diagnostics_summary(row)


def get_top_feature_diagnostics_summaries(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        summary_id,
        feature_key,
        symbol,
        interval,
        winner_avg,
        loser_avg,
        winner_count,
        loser_count,
        diagnostic_score,
        updated_at
    FROM feature_diagnostics_summary
    WHERE symbol = %s
      AND interval = %s
    ORDER BY diagnostic_score DESC, summary_id ASC
    LIMIT %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval, limit))
        rows = cursor.fetchall()

    return [_row_to_feature_diagnostics_summary(row) for row in rows]