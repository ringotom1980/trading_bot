"""
Path: storage/repositories/system_state_repo.py
說明：系統主狀態資料表存取層，負責查詢、初始化與更新唯一一筆 system_state。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def get_system_state(conn: PgConnection, state_id: int = 1) -> dict[str, Any] | None:
    """
    功能：依主鍵查詢 system_state。
    參數：
        conn: PostgreSQL 連線物件。
        state_id: system_state 主鍵，預設為 1。
    回傳：
        system_state 資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        id,
        engine_mode,
        trade_mode,
        trading_state,
        live_armed,
        active_strategy_version_id,
        primary_symbol,
        primary_interval,
        current_position_side,
        current_position_id,
        last_bar_close_time,
        last_decision_id,
        last_order_id,
        last_trade_id,
        last_heartbeat_at,
        updated_at,
        updated_by,
        note
    FROM system_state
    WHERE id = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (state_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "engine_mode": row[1],
        "trade_mode": row[2],
        "trading_state": row[3],
        "live_armed": row[4],
        "active_strategy_version_id": row[5],
        "primary_symbol": row[6],
        "primary_interval": row[7],
        "current_position_side": row[8],
        "current_position_id": row[9],
        "last_bar_close_time": row[10],
        "last_decision_id": row[11],
        "last_order_id": row[12],
        "last_trade_id": row[13],
        "last_heartbeat_at": row[14],
        "updated_at": row[15],
        "updated_by": row[16],
        "note": row[17],
    }


def create_initial_system_state(
    conn: PgConnection,
    active_strategy_version_id: int,
    primary_symbol: str,
    primary_interval: str,
) -> None:
    """
    功能：建立第一筆 system_state 初始資料。
    參數：
        conn: PostgreSQL 連線物件。
        active_strategy_version_id: 目前啟用的策略版本 ID。
        primary_symbol: 主交易標的。
        primary_interval: 主交易週期。
    """
    sql = """
    INSERT INTO system_state (
        id,
        engine_mode,
        trade_mode,
        trading_state,
        live_armed,
        active_strategy_version_id,
        primary_symbol,
        primary_interval,
        updated_at,
        updated_by,
        note
    )
    VALUES (
        1,
        'REALTIME',
        'TESTNET',
        'OFF',
        FALSE,
        %s,
        %s,
        %s,
        NOW(),
        'seed_strategy',
        '初始 system_state'
    )
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                active_strategy_version_id,
                primary_symbol,
                primary_interval,
            ),
        )


def update_current_position(
    conn: PgConnection,
    *,
    state_id: int,
    current_position_id: int | None,
    current_position_side: str | None,
    updated_by: str,
) -> None:
    """
    功能：更新 system_state 的目前持倉欄位。
    參數：
        conn: PostgreSQL 連線物件。
        state_id: system_state 主鍵。
        current_position_id: 目前持倉 ID，可為 None。
        current_position_side: 目前持倉方向，可為 LONG、SHORT 或 None。
        updated_by: 更新來源說明。
    """
    sql = """
    UPDATE system_state
    SET
        current_position_id = %s,
        current_position_side = %s,
        updated_at = NOW(),
        updated_by = %s
    WHERE id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                current_position_id,
                current_position_side,
                updated_by,
                state_id,
            ),
        )


def update_runtime_refs(
    conn: PgConnection,
    *,
    state_id: int,
    last_bar_close_time: datetime | None,
    last_decision_id: int | None,
    last_order_id: int | None,
    last_trade_id: int | None,
    updated_by: str,
) -> None:
    """
    功能：更新 system_state 的 runtime 最後參照欄位。
    參數：
        conn: PostgreSQL 連線物件。
        state_id: system_state 主鍵。
        last_bar_close_time: 最後處理的 bar 收線時間。
        last_decision_id: 最後一筆 decision_id。
        last_order_id: 最後一筆 order_id。
        last_trade_id: 最後一筆 trade_id。
        updated_by: 更新來源說明。
    """
    sql = """
    UPDATE system_state
    SET
        last_bar_close_time = %s,
        last_decision_id = %s,
        last_order_id = %s,
        last_trade_id = %s,
        updated_at = NOW(),
        updated_by = %s
    WHERE id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                last_bar_close_time,
                last_decision_id,
                last_order_id,
                last_trade_id,
                updated_by,
                state_id,
            ),
        )
        
def update_active_strategy_version(
    conn: PgConnection,
    *,
    state_id: int,
    active_strategy_version_id: int,
    updated_by: str,
) -> None:
    """
    功能：更新 system_state.active_strategy_version_id。
    """
    sql = """
    UPDATE system_state
    SET
        active_strategy_version_id = %s,
        updated_at = NOW(),
        updated_by = %s
    WHERE id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (active_strategy_version_id, updated_by, state_id),
        )