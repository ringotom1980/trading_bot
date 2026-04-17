"""
Path: storage/repositories/governor_decisions_repo.py
說明：governor_decisions 資料表存取層。
"""

from __future__ import annotations

import json
from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_governor_decision(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "decision_id": row[0],
        "run_key": row[1],
        "decision_type": row[2],
        "target_type": row[3],
        "target_key": row[4],
        "action": row[5],
        "before_value_json": row[6],
        "after_value_json": row[7],
        "reason_json": row[8],
        "created_at": row[9],
    }


def create_governor_decision(
    conn: PgConnection,
    *,
    run_key: str,
    decision_type: str,
    target_type: str,
    target_key: str,
    action: str,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
    reason: dict[str, Any] | None = None,
) -> int:
    sql = """
    INSERT INTO governor_decisions (
        run_key,
        decision_type,
        target_type,
        target_key,
        action,
        before_value_json,
        after_value_json,
        reason_json
    )
    VALUES (
        %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb
    )
    RETURNING decision_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                run_key,
                decision_type,
                target_type,
                target_key,
                action,
                json.dumps(before_value, ensure_ascii=False, sort_keys=True) if before_value is not None else None,
                json.dumps(after_value, ensure_ascii=False, sort_keys=True) if after_value is not None else None,
                json.dumps(reason or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 governor_decisions 失敗：未取得 decision_id")

    return int(row[0])


def get_latest_governor_decision(
    conn: PgConnection,
) -> dict[str, Any] | None:
    sql = """
    SELECT
        decision_id,
        run_key,
        decision_type,
        target_type,
        target_key,
        action,
        before_value_json,
        after_value_json,
        reason_json,
        created_at
    FROM governor_decisions
    ORDER BY decision_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_governor_decision(row)


def get_governor_decisions_by_run_key(
    conn: PgConnection,
    *,
    run_key: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        decision_id,
        run_key,
        decision_type,
        target_type,
        target_key,
        action,
        before_value_json,
        after_value_json,
        reason_json,
        created_at
    FROM governor_decisions
    WHERE run_key = %s
    ORDER BY decision_id ASC
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (run_key,))
        rows = cursor.fetchall()

    return [_row_to_governor_decision(row) for row in rows]