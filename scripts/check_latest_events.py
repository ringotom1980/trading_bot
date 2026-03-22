"""
Path: scripts/check_latest_events.py
說明：查看最近 system_events，方便確認 candidate search / promote 是否有留下事件軌跡。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope


def main() -> None:
    sql = """
    SELECT
        system_event_id,
        event_type,
        event_level,
        source,
        message,
        created_by,
        created_at
    FROM system_events
    ORDER BY system_event_id DESC
    LIMIT 20
    """

    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

    print("latest system events:")
    for row in rows:
        print(
            f"id={row[0]} | type={row[1]} | level={row[2]} | source={row[3]} | "
            f"created_by={row[5]} | created_at={row[6]} | message={row[4]}"
        )


if __name__ == "__main__":
    main()