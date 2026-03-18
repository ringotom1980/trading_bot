"""
Path: storage/db.py
說明：集中管理 PostgreSQL 連線與基本連線測試功能，提供全專案共用的資料庫入口。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as PgConnection

from config.settings import load_settings


def build_dsn() -> str:
    """
    功能：依目前設定組合 PostgreSQL DSN 連線字串。
    回傳：
        可供 psycopg2 使用的 DSN 字串。
    """
    settings = load_settings()

    return (
        f"host={settings.db_host} "
        f"port={settings.db_port} "
        f"dbname={settings.db_name} "
        f"user={settings.db_user} "
        f"password={settings.db_password}"
    )


def get_connection() -> PgConnection:
    """
    功能：建立一個新的 PostgreSQL 連線。
    回傳：
        psycopg2 PostgreSQL 連線物件。
    """
    dsn = build_dsn()
    return psycopg2.connect(dsn)


@contextmanager
def connection_scope() -> Iterator[PgConnection]:
    """
    功能：提供具自動提交/回滾/關閉的資料庫連線範圍。
    回傳：
        可於 with 區塊中使用的 PostgreSQL 連線物件。
    """
    conn = get_connection()

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_connection() -> tuple[bool, str]:
    """
    功能：測試 PostgreSQL 連線是否正常。
    回傳：
        (是否成功, 訊息)
    """
    try:
        with connection_scope() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT version();")
                row = cursor.fetchone()

        version_text = row[0] if row else "unknown"
        return True, f"資料庫連線成功：{version_text}"
    except Exception as exc:
        return False, f"資料庫連線失敗：{exc}"