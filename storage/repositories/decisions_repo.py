"""
Path: storage/repositories/decisions_repo.py
說明：決策紀錄資料表存取層，負責新增、查詢與更新 decisions_log。
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


def get_decision_by_bar_close_time(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    bar_close_time: datetime,
) -> dict[str, Any] | None:
    """
    功能：依 symbol、interval、bar_close_time 查詢是否已存在 decision。
    參數：
        conn: PostgreSQL 連線物件。
        symbol: 交易標的。
        interval: 週期。
        bar_close_time: K 線收線時間。
    回傳：
        decision 資料字典；若不存在則回傳 None。
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
    WHERE symbol = %s
      AND interval = %s
      AND bar_close_time = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval, bar_close_time))
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
    
def get_latest_decision_by_symbol_interval(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
) -> dict[str, Any] | None:
    """
    功能：查詢指定 symbol / interval 最新一筆 decisions_log。
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
    WHERE symbol = %s
      AND interval = %s
    ORDER BY bar_close_time DESC, decision_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (symbol, interval))
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
    
    
def update_decision_log(
    conn: PgConnection,
    *,
    decision_id: int,
    decision: str,
    decision_score: float | None,
    reason_code: str | None,
    reason_summary: str | None,
    features: dict[str, Any] | None,
    position_id_before: int | None,
    position_side_before: str | None,
    position_side_after: str | None,
) -> None:
    """
    功能：更新既有 decisions_log 的決策內容，避免同一根 bar 重複插入新資料。
    """
    sql = """
    UPDATE decisions_log
    SET
        decision = %s,
        decision_score = %s,
        reason_code = %s,
        reason_summary = %s,
        features_json = %s::jsonb,
        position_id_before = %s,
        position_side_before = %s,
        position_side_after = %s
    WHERE decision_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                decision,
                decision_score,
                reason_code,
                reason_summary,
                json.dumps(features, ensure_ascii=False) if features is not None else None,
                position_id_before,
                position_side_before,
                position_side_after,
                decision_id,
            ),
        )


def mark_decision_executed(
    conn: PgConnection,
    *,
    decision_id: int,
    executed: bool,
    position_id_after: int | None = None,
    position_side_after: str | None = None,
    linked_order_id: int | None = None,
) -> None:
    """
    功能：更新 decisions_log 的 executed 狀態與執行後關聯資訊。
    參數：
        conn: PostgreSQL 連線物件。
        decision_id: 決策主鍵。
        executed: 是否已執行。
        position_id_after: 執行後持倉 ID。
        position_side_after: 執行後持倉方向。
        linked_order_id: 關聯委託單 ID。
    """
    sql = """
    UPDATE decisions_log
    SET
        executed = %s,
        position_id_after = %s,
        position_side_after = %s,
        linked_order_id = %s
    WHERE decision_id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                executed,
                position_id_after,
                position_side_after,
                linked_order_id,
                decision_id,
            ),
        )