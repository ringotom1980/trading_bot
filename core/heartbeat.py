"""
Path: core/heartbeat.py
說明：系統心跳更新模組，負責寫入 system_state 的最後心跳時間。
"""

from __future__ import annotations

from psycopg2.extensions import connection as PgConnection


def touch_system_heartbeat(conn: PgConnection, state_id: int = 1, updated_by: str = "runtime") -> None:
    """
    功能：更新 system_state 的最後心跳時間與更新資訊。
    參數：
        conn: PostgreSQL 連線物件。
        state_id: system_state 主鍵，預設為 1。
        updated_by: 更新來源說明。
    """
    sql = """
    UPDATE system_state
    SET
        last_heartbeat_at = NOW(),
        updated_at = NOW(),
        updated_by = %s
    WHERE id = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (updated_by, state_id))