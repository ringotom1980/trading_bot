"""
Path: scripts/apply_schema_009.py
說明：套用 009_candidate_walk_forward.sql。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope

SCHEMA_PATH = ROOT_DIR / "storage" / "schema" / "009_candidate_walk_forward.sql"


def main() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"找不到 schema 檔案：{SCHEMA_PATH}")

    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)

    print("apply schema 009 完成")
    print(f"schema_path={SCHEMA_PATH}")


if __name__ == "__main__":
    main()