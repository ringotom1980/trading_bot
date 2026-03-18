"""
Path: storage/repositories/decisions_repo.py
說明：決策紀錄資料表存取層，負責新增與查詢 decisions_log。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def insert_decision_log(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    bar_open_time: datetime,
    bar_close_time: datetime,
    engine_mode: str,
    trade_mode: str | None,
    strategy_version_id: int,
    position_id_before: int | None,
    position_side_before: str | None,
    decision: str,
    decision_score: float | None,
    reason_code: str | None,
    reason_summary: str | None,
    features: dict[str, Any] | None,
    executed: bool,
    position_id_after: int | None = None,
    position_side_after: str | None = None,
    linked_order_id: int | None = None,
) -> int:
    """
    功能：新增一筆 decisions_log 紀錄。
    回傳：
        新建立的 decision_id。
    """
    sql = """
    INSERT INTO decisions_log (
        symbol,
        interval,
        bar_open_time,
        bar_close_time,
        engine_mode,
        trade_mode,
        strategy_version_id,
        position_id_before,
        position_side_before,
        decision,
        decision_score,
        reason_code,
        reason_summary,
        features_json,
        executed,
        position_id_after,
        position_side_after,
        linked_order_id
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
    )
    RETURNING decision_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                symbol,
                interval,
                bar_open_time,
                bar_close_time,
                engine_mode,
                trade_mode,
                strategy_version_id,
                position_id_before,
                position_side_before,
                decision,
                decision_score,
                reason_code,
                reason_summary,
                json.dumps(features, ensure_ascii=False) if features is not None else None,
                executed,
                position_id_after,
                position_side_after,
                linked_order_id,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 decisions_log 失敗：未取得 decision_id")

    return int(row[0])


def get_latest_decision_log(conn: PgConnection) -> dict[str, Any] | None:
    """
    功能：查詢最新一筆 decisions_log。
    回傳：
        最新 decision 資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        decision_id,
        symbol,
        interval,
        bar_open_time,
        bar_close_time,
        engine_mode,
        trade_mode,
        strategy_version_id,
        position_id_before,
        position_side_before,
        decision,
        decision_score,
        reason_code,
        reason_summary,
        features_json,
        executed,
        position_id_after,
        position_side_after,
        linked_order_id,
        created_at
    FROM decisions_log
    ORDER BY decision_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "decision_id": row[0],
        "symbol": row[1],
        "interval": row[2],
        "bar_open_time": row[3],
        "bar_close_time": row[4],
        "engine_mode": row[5],
        "trade_mode": row[6],
        "strategy_version_id": row[7],
        "position_id_before": row[8],
        "position_side_before": row[9],
        "decision": row[10],
        "decision_score": float(row[11]) if row[11] is not None else None,
        "reason_code": row[12],
        "reason_summary": row[13],
        "features_json": row[14],
        "executed": row[15],
        "position_id_after": row[16],
        "position_side_after": row[17],
        "linked_order_id": row[18],
        "created_at": row[19],
    }