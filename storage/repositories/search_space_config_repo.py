"""
Path: storage/repositories/search_space_config_repo.py
說明：search_space_config 資料表存取層。
"""

from __future__ import annotations

import json
from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_search_space_config(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "config_id": row[0],
        "scope_key": row[1],
        "config_version": row[2],
        "is_active": row[3],
        "config_json": row[4],
        "created_by": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def create_search_space_config(
    conn: PgConnection,
    *,
    scope_key: str,
    config_version: int,
    is_active: bool,
    config: dict[str, Any],
    created_by: str | None = None,
) -> int:
    sql = """
    INSERT INTO search_space_config (
        scope_key,
        config_version,
        is_active,
        config_json,
        created_by,
        created_at,
        updated_at
    )
    VALUES (
        %s, %s, %s, %s::jsonb, %s, NOW(), NOW()
    )
    RETURNING config_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                scope_key,
                config_version,
                is_active,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                created_by,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 search_space_config 失敗：未取得 config_id")

    return int(row[0])


def deactivate_search_space_configs_by_scope(
    conn: PgConnection,
    *,
    scope_key: str,
) -> None:
    sql = """
    UPDATE search_space_config
    SET
        is_active = FALSE,
        updated_at = NOW()
    WHERE scope_key = %s
      AND is_active = TRUE
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (scope_key,))


def replace_active_search_space_config(
    conn: PgConnection,
    *,
    scope_key: str,
    config: dict[str, Any],
    created_by: str | None = None,
) -> int:
    sql = """
    SELECT COALESCE(MAX(config_version), 0)
    FROM search_space_config
    WHERE scope_key = %s
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (scope_key,))
        row = cursor.fetchone()

    current_max_version = int(row[0]) if row is not None and row[0] is not None else 0
    new_version = current_max_version + 1

    deactivate_search_space_configs_by_scope(conn, scope_key=scope_key)

    return create_search_space_config(
        conn,
        scope_key=scope_key,
        config_version=new_version,
        is_active=True,
        config=config,
        created_by=created_by,
    )


def get_active_search_space_config(
    conn: PgConnection,
    *,
    scope_key: str,
) -> dict[str, Any] | None:
    sql = """
    SELECT
        config_id,
        scope_key,
        config_version,
        is_active,
        config_json,
        created_by,
        created_at,
        updated_at
    FROM search_space_config
    WHERE scope_key = %s
      AND is_active = TRUE
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (scope_key,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_search_space_config(row)


def get_latest_search_space_config(
    conn: PgConnection,
    *,
    scope_key: str,
) -> dict[str, Any] | None:
    sql = """
    SELECT
        config_id,
        scope_key,
        config_version,
        is_active,
        config_json,
        created_by,
        created_at,
        updated_at
    FROM search_space_config
    WHERE scope_key = %s
    ORDER BY config_version DESC, config_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (scope_key,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_search_space_config(row)