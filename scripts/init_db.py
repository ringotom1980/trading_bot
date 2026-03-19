"""
Path: scripts/init_db.py
說明：初始化資料庫結構，依序讀取 storage/schema 目錄下的 .sql 檔並執行建表流程。
"""

from __future__ import annotations

from pathlib import Path

from config.logging import get_logger, setup_logging
from storage.db import connection_scope, test_connection


def get_schema_dir_path() -> Path:
    """
    功能：取得 schema 目錄路徑。
    回傳：
        schema 目錄 Path 物件。
    """
    return Path(__file__).resolve().parent.parent / "storage" / "schema"


def get_schema_file_paths() -> list[Path]:
    """
    功能：取得所有 schema SQL 檔，並依檔名排序。
    回傳：
        schema SQL 檔案 Path 清單。
    """
    schema_dir = get_schema_dir_path()

    if not schema_dir.exists():
        raise FileNotFoundError(f"找不到 schema 目錄：{schema_dir}")

    schema_files = sorted(schema_dir.glob("*.sql"))
    if not schema_files:
        raise FileNotFoundError(f"schema 目錄內沒有 .sql 檔：{schema_dir}")

    return schema_files


def read_schema_sql(schema_path: Path) -> str:
    """
    功能：讀取單一 schema SQL 檔內容。
    參數：
        schema_path: schema SQL 檔路徑。
    回傳：
        完整 SQL 字串內容。
    """
    if not schema_path.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{schema_path}")

    return schema_path.read_text(encoding="utf-8")


def initialize_database() -> None:
    """
    功能：依序執行 schema 目錄中的 SQL 檔，建立資料表。
    """
    logger = get_logger("scripts.init_db")
    schema_files = get_schema_file_paths()

    with connection_scope() as conn:
        with conn.cursor() as cursor:
            for schema_path in schema_files:
                sql_text = read_schema_sql(schema_path)
                cursor.execute(sql_text)
                logger.info("已執行 schema：%s", schema_path.name)

    logger.info("資料庫初始化完成：全部 schema 已執行")


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