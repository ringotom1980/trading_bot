"""
Path: storage/repositories/strategy_versions_repo.py
說明：策略版本資料表存取層，負責查詢、建立與檢查 strategy_versions 資料。
"""

from __future__ import annotations

import json
from typing import Any

from psycopg2.extensions import connection as PgConnection


def get_strategy_version_by_code(conn: PgConnection, version_code: str) -> dict[str, Any] | None:
    """
    功能：依 version_code 查詢單一策略版本。
    參數：
        conn: PostgreSQL 連線物件。
        version_code: 策略版本代碼。
    回傳：
        查詢到的策略版本資料字典；若不存在則回傳 None。
    """
    sql = """
    SELECT
        strategy_version_id,
        version_code,
        status,
        source_type,
        base_version_id,
        symbol,
        interval,
        feature_set_json,
        params_json,
        backtest_summary_json,
        validation_summary_json,
        promotion_score,
        is_candidate,
        created_at,
        activated_at,
        retired_at,
        note
    FROM strategy_versions
    WHERE version_code = %s
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, (version_code,))
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "strategy_version_id": row[0],
        "version_code": row[1],
        "status": row[2],
        "source_type": row[3],
        "base_version_id": row[4],
        "symbol": row[5],
        "interval": row[6],
        "feature_set_json": row[7],
        "params_json": row[8],
        "backtest_summary_json": row[9],
        "validation_summary_json": row[10],
        "promotion_score": row[11],
        "is_candidate": row[12],
        "created_at": row[13],
        "activated_at": row[14],
        "retired_at": row[15],
        "note": row[16],
    }


def create_strategy_version(
    conn: PgConnection,
    version_code: str,
    status: str,
    source_type: str,
    symbol: str,
    interval: str,
    feature_set: dict[str, Any],
    params: dict[str, Any],
    note: str | None = None,
) -> int:
    """
    功能：建立一筆新的策略版本資料。
    參數：
        conn: PostgreSQL 連線物件。
        version_code: 策略版本代碼。
        status: 策略狀態。
        source_type: 策略來源類型。
        symbol: 交易標的。
        interval: 交易週期。
        feature_set: 特徵集合定義。
        params: 策略參數。
        note: 備註。
    回傳：
        新建立的 strategy_version_id。
    """
    sql = """
    INSERT INTO strategy_versions (
        version_code,
        status,
        source_type,
        symbol,
        interval,
        feature_set_json,
        params_json,
        is_candidate,
        activated_at,
        note
    )
    VALUES (
        %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, NOW(), %s
    )
    RETURNING strategy_version_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                version_code,
                status,
                source_type,
                symbol,
                interval,
                json.dumps(feature_set, ensure_ascii=False),
                json.dumps(params, ensure_ascii=False),
                False,
                note,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 strategy_versions 失敗：未取得 strategy_version_id")

    return int(row[0])