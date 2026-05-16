"""
Path: scripts/apply_schema_004.py
說明：執行 trades_log 第四版 schema，建立完整交易結果資料表。
"""

from __future__ import annotations

from pathlib import Path

from config.logging import get_logger, setup_logging
from storage.db import connection_scope, test_connection


def get_schema_file_path() -> Path:
    """
    功能：取得 004 schema SQL 檔路徑。
    """
    return Path(__file__).resolve().parent.parent / "storage" / "schema" / "004_trades_log.sql"


def main() -> None:
    """
    功能：執行 schema 004 主入口。
    """
    setup_logging()
    logger = get_logger("scripts.apply_schema_004")

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

    logger.info("資料庫初始化完成：004_trades_log.sql 已執行")


if __name__ == "__main__":
    main()