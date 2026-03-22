"""
Path: storage/repositories/strategy_candidates_repo.py
說明：strategy_candidates 資料表存取層，負責建立、查詢、更新 candidate 結果。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_strategy_candidate(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "candidate_id": row[0],
        "source_strategy_version_id": row[1],
        "symbol": row[2],
        "interval": row[3],
        "tested_range_start": row[4],
        "tested_range_end": row[5],
        "candidate_no": row[6],
        "params_json": row[7],
        "metrics_json": row[8],
        "rank_score": float(row[9]),
        "candidate_status": row[10],
        "note": row[11],
        "created_at": row[12],
    }


def upsert_strategy_candidate(
    conn: PgConnection,
    *,
    source_strategy_version_id: int,
    symbol: str,
    interval: str,
    tested_range_start: datetime,
    tested_range_end: datetime,
    candidate_no: int,
    params: dict[str, Any],
    metrics: dict[str, Any],
    rank_score: float,
    note: str | None = None,
) -> int:
    """
    功能：建立或覆蓋同一來源版本/同一測試區間/同一 candidate_no 的 candidate 結果。
    回傳：
        candidate_id
    """
    sql = """
    INSERT INTO strategy_candidates (
        source_strategy_version_id,
        symbol,
        interval,
        tested_range_start,
        tested_range_end,
        candidate_no,
        params_json,
        metrics_json,
        rank_score,
        note
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s
    )
    ON CONFLICT (
        source_strategy_version_id,
        symbol,
        interval,
        tested_range_start,
        tested_range_end,
        candidate_no
    )
    DO UPDATE SET
        params_json = EXCLUDED.params_json,
        metrics_json = EXCLUDED.metrics_json,
        rank_score = EXCLUDED.rank_score,
        note = EXCLUDED.note
    RETURNING candidate_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                source_strategy_version_id,
                symbol,
                interval,
                tested_range_start,
                tested_range_end,
                candidate_no,
                json.dumps(params, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False),
                rank_score,
                note,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 strategy_candidates 失敗：未取得 candidate_id")

    return int(row[0])


def get_top_strategy_candidates(
    conn: PgConnection,
    *,
    source_strategy_version_id: int,
    symbol: str,
    interval: str,
    tested_range_start: datetime,
    tested_range_end: datetime,
    limit: int = 10,
    ignore_range: bool = False,
) -> list[dict[str, Any]]:
    """
    功能：查詢指定來源版本的 top candidates。
    說明：
        - 預設會依 tested_range_start / tested_range_end 篩選
        - ignore_range=True 時，忽略區間，只抓該版本/symbol/interval 下 top candidates
    """
    if ignore_range:
        sql = """
        SELECT
            candidate_id,
            source_strategy_version_id,
            symbol,
            interval,
            tested_range_start,
            tested_range_end,
            candidate_no,
            params_json,
            metrics_json,
            rank_score,
            candidate_status,
            note,
            created_at
        FROM strategy_candidates
        WHERE source_strategy_version_id = %s
          AND symbol = %s
          AND interval = %s
        ORDER BY rank_score DESC, candidate_no ASC
        LIMIT %s
        """

        params = (
            source_strategy_version_id,
            symbol,
            interval,
            limit,
        )
    else:
        sql = """
        SELECT
            candidate_id,
            source_strategy_version_id,
            symbol,
            interval,
            tested_range_start,
            tested_range_end,
            candidate_no,
            params_json,
            metrics_json,
            rank_score,
            candidate_status,
            note,
            created_at
        FROM strategy_candidates
        WHERE source_strategy_version_id = %s
          AND symbol = %s
          AND interval = %s
          AND tested_range_start = %s
          AND tested_range_end = %s
        ORDER BY rank_score DESC, candidate_no ASC
        LIMIT %s
        """

        params = (
            source_strategy_version_id,
            symbol,
            interval,
            tested_range_start,
            tested_range_end,
            limit,
        )

    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    return [_row_to_strategy_candidate(row) for row in rows]


def update_strategy_candidate_status(
    conn: PgConnection,
    *,
    candidate_id: int,
    candidate_status: str,
    note: str | None = None,
) -> None:
    """
    功能：更新 candidate 狀態。
    """
    sql = """
    UPDATE strategy_candidates
    SET
        candidate_status = %s,
        note = %s
    WHERE candidate_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (candidate_status, note, candidate_id))


def update_strategy_candidate_validation_result(
    conn: PgConnection,
    *,
    candidate_id: int,
    validation_status: str,
    validation_payload: dict[str, Any],
) -> None:
    """
    功能：將 validation 結果寫回 candidate_status 與 note。
    說明：
        - v1 不改 schema
        - validation 結果序列化到 note
        - candidate_status 只使用既有允許值
    """
    mapped_status = "APPROVED" if validation_status == "VALIDATED_PASS" else "REJECTED"

    sql = """
    UPDATE strategy_candidates
    SET
        candidate_status = %s,
        note = %s
    WHERE candidate_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                mapped_status,
                json.dumps(validation_payload, ensure_ascii=False, sort_keys=True),
                candidate_id,
            ),
        )


def get_strategy_candidate_by_id(
    conn: PgConnection,
    *,
    candidate_id: int,
) -> dict[str, Any] | None:
    """
    功能：依 candidate_id 查詢單筆 candidate。
    """
    sql = """
    SELECT
        candidate_id,
        source_strategy_version_id,
        symbol,
        interval,
        tested_range_start,
        tested_range_end,
        candidate_no,
        params_json,
        metrics_json,
        rank_score,
        candidate_status,
        note,
        created_at
    FROM strategy_candidates
    WHERE candidate_id = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (candidate_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_strategy_candidate(row)