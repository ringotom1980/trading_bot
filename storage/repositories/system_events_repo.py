"""
Path: storage/repositories/system_events_repo.py
說明：系統事件資料表存取層，負責安全寫入與查詢 system_events；若資料表尚未建立，則自動略過不報錯。
"""

from __future__ import annotations

import json
from typing import Any

from psycopg2.extensions import connection as PgConnection


def system_events_table_exists(conn: PgConnection) -> bool:
    """
    功能：檢查 system_events 資料表是否存在。
    參數：
        conn: PostgreSQL 連線物件。
    回傳：
        若存在則回傳 True，否則回傳 False。
    """
    sql = "SELECT to_regclass('system_events')"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    return row is not None and row[0] is not None


def create_system_event(
    conn: PgConnection,
    *,
    event_type: str,
    event_level: str,
    source: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    created_by: str | None = None,
    engine_mode_before: str | None = None,
    engine_mode_after: str | None = None,
    trade_mode_before: str | None = None,
    trade_mode_after: str | None = None,
    trading_state_before: str | None = None,
    trading_state_after: str | None = None,
    live_armed_before: bool | None = None,
    live_armed_after: bool | None = None,
    strategy_version_before: int | None = None,
    strategy_version_after: int | None = None,
) -> int | None:
    """
    功能：建立一筆 system_events 紀錄；若 system_events 表尚未建立，則略過。
    參數：
        conn: PostgreSQL 連線物件。
        其餘參數對應 system_events 欄位。
    回傳：
        若成功寫入則回傳 event_id；若資料表不存在則回傳 None。
    """
    if not system_events_table_exists(conn):
        return None

    sql = """
    INSERT INTO system_events (
        event_type,
        event_level,
        source,
        engine_mode_before,
        engine_mode_after,
        trade_mode_before,
        trade_mode_after,
        trading_state_before,
        trading_state_after,
        live_armed_before,
        live_armed_after,
        strategy_version_before,
        strategy_version_after,
        message,
        details_json,
        created_by,
        created_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW()
    )
    RETURNING event_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                event_type,
                event_level,
                source,
                engine_mode_before,
                engine_mode_after,
                trade_mode_before,
                trade_mode_after,
                trading_state_before,
                trading_state_after,
                live_armed_before,
                live_armed_after,
                strategy_version_before,
                strategy_version_after,
                message,
                json.dumps(details, ensure_ascii=False) if details is not None else None,
                created_by,
            ),
        )
        row = cursor.fetchone()

    return int(row[0]) if row is not None else None


def get_latest_system_event(conn: PgConnection) -> dict[str, Any] | None:
    """
    功能：查詢最新一筆 system_events。
    參數：
        conn: PostgreSQL 連線物件。
    回傳：
        最新事件資料字典；若資料表不存在或無資料則回傳 None。
    """
    if not system_events_table_exists(conn):
        return None

    sql = """
    SELECT
        event_id,
        event_type,
        event_level,
        source,
        engine_mode_before,
        engine_mode_after,
        trade_mode_before,
        trade_mode_after,
        trading_state_before,
        trading_state_after,
        live_armed_before,
        live_armed_after,
        strategy_version_before,
        strategy_version_after,
        message,
        details_json,
        created_by,
        created_at
    FROM system_events
    ORDER BY event_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "event_id": row[0],
        "event_type": row[1],
        "event_level": row[2],
        "source": row[3],
        "engine_mode_before": row[4],
        "engine_mode_after": row[5],
        "trade_mode_before": row[6],
        "trade_mode_after": row[7],
        "trading_state_before": row[8],
        "trading_state_after": row[9],
        "live_armed_before": row[10],
        "live_armed_after": row[11],
        "strategy_version_before": row[12],
        "strategy_version_after": row[13],
        "message": row[14],
        "details_json": row[15],
        "created_by": row[16],
        "created_at": row[17],
    }


def get_system_event_count(conn: PgConnection) -> int:
    """
    功能：查詢 system_events 總筆數。
    參數：
        conn: PostgreSQL 連線物件。
    回傳：
        system_events 總筆數；若資料表不存在則回傳 0。
    """
    if not system_events_table_exists(conn):
        return 0

    sql = "SELECT COUNT(*) FROM system_events"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    return int(row[0]) if row is not None else 0