"""
Path: scripts/apply_schema_003.py
說明：執行 positions 第三版 schema，建立持倉生命週期資料表。
"""

from __future__ import annotations

from pathlib import Path

from config.logging import get_logger, setup_logging
from storage.db import connection_scope, test_connection


def get_schema_file_path() -> Path:
    """
    功能：取得 003 schema SQL 檔路徑。
    """
    return Path(__file__).resolve().parent.parent / "storage" / "schema" / "003_positions.sql"


def main() -> None:
    """
    功能：執行 schema 003 主入口。
    """
    setup_logging()
    logger = get_logger("scripts.apply_schema_003")

    ok, message = test_connection()
    if not ok:
        logger.error(message)
        raise SystemExit(1)

    logger.info(message)

    schema_path = get_schema_file_path()
    sql_text = schema_path.read_text(encoding="utf-8")

    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql_text)

    logger.info("資料庫初始化完成：003_positions.sql 已執行")


if __name__ == "__main__":
    main()