"""
Path: services/strategy_service.py
說明：策略服務層，負責讀取目前 ACTIVE 策略，供主程式與後續決策流程使用。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as PgConnection

from storage.repositories.strategy_versions_repo import get_active_strategy_version


def load_active_strategy(conn: PgConnection) -> dict[str, Any]:
    """
    功能：讀取目前唯一 ACTIVE 的策略版本。
    參數：
        conn: PostgreSQL 連線物件。
    回傳：
        ACTIVE 策略版本資料字典。
    """
    strategy = get_active_strategy_version(conn)

    if strategy is None:
        raise RuntimeError("找不到 ACTIVE 策略版本，請先執行 seed_strategy")

    return strategy