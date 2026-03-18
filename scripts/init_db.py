"""
Path: scripts/init_db.py
說明：初始化資料庫結構，讀取 schema SQL 檔並執行第一版建表流程。
"""

from __future__ import annotations

from pathlib import Path

from config.logging import get_logger, setup_logging
from storage.db import connection_scope, test_connection


def get_schema_file_path() -> Path:
    """
    功能：取得第一版 schema SQL 檔路徑。
    回傳：
        schema SQL 檔案 Path 物件。
    """
    return Path(__file__).resolve().parent.parent / "storage" / "schema" / "001_init.sql"


def read_schema_sql() -> str:
    """
    功能：讀取 schema SQL 檔內容。
    回傳：
        完整 SQL 字串內容。
    """
    schema_path = get_schema_file_path()

    if not schema_path.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{schema_path}")

    return schema_path.read_text(encoding="utf-8")


def initialize_database() -> None:
    """
    功能：執行第一版 schema，建立基礎資料表。
    """
    logger = get_logger("scripts.init_db")
    sql_text = read_schema_sql()

    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql_text)

    logger.info("資料庫初始化完成：001_init.sql 已執行")


def main() -> None:
    """
    功能：資料庫初始化腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.init_db")

    ok, message = test_connection()
    if not ok:
        logger.error(message)
        raise SystemExit(1)

    logger.info(message)
    initialize_database()


if __name__ == "__main__":
    main()