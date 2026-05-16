"""
Path: scripts/apply_schema_007.py
說明：套用 007_strategy_candidates.sql。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope


def main() -> None:
    schema_path = ROOT_DIR / "storage" / "schema" / "007_strategy_candidates.sql"
    sql = schema_path.read_text(encoding="utf-8")

    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)

    print("007_strategy_candidates.sql 套用完成")


if __name__ == "__main__":
    main()