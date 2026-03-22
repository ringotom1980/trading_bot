"""
Path: scripts/check_latest_events.py
說明：查看最近 system_events，避免寫死欄位名稱。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope


def _pick_first(columns: list[str], candidates: list[str]) -> str | None:
    for name in candidates:
        if name in columns:
            return name
    return None


def main() -> None:
    with connection_scope() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'system_events'
                ORDER BY ordinal_position
                """
            )
            columns = [row[0] for row in cursor.fetchall()]

            if not columns:
                raise RuntimeError("找不到 system_events 資料表或欄位")

            id_col = _pick_first(columns, ["system_event_id", "event_id", "id"])
            event_type_col = _pick_first(columns, ["event_type"])
            event_level_col = _pick_first(columns, ["event_level"])
            source_col = _pick_first(columns, ["source"])
            message_col = _pick_first(columns, ["message"])
            created_by_col = _pick_first(columns, ["created_by"])
            created_at_col = _pick_first(columns, ["created_at"])

            select_cols: list[str] = []
            if id_col:
                select_cols.append(id_col)
            if event_type_col:
                select_cols.append(event_type_col)
            if event_level_col:
                select_cols.append(event_level_col)
            if source_col:
                select_cols.append(source_col)
            if message_col:
                select_cols.append(message_col)
            if created_by_col:
                select_cols.append(created_by_col)
            if created_at_col:
                select_cols.append(created_at_col)

            if not select_cols:
                raise RuntimeError("system_events 找不到可顯示的欄位")

            order_col = created_at_col or id_col or columns[0]

            sql = f"""
            SELECT {", ".join(select_cols)}
            FROM system_events
            ORDER BY {order_col} DESC
            LIMIT 20
            """
            cursor.execute(sql)
            rows = cursor.fetchall()

    print("latest system events:")
    for row in rows:
        parts = []
        for idx, col in enumerate(select_cols):
            parts.append(f"{col}={row[idx]}")
        print(" | ".join(parts))


if __name__ == "__main__":
    main()