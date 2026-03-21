"""
Path: services/executors/live_executor.py
說明：LIVE 執行器骨架，先保留介面與回傳格式，後續接 exchange/order_executor.py 與 Binance 真實下單流程。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings


def create_live_entry_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_result: dict[str, Any],
    decision_id: int,
) -> tuple[int | None, int | None, str | None, str]:
    """
    功能：LIVE 開倉骨架。
    回傳：
        (linked_order_id, position_id_after, position_side_after, guard_reason)
    """
    return None, None, None, "LIVE executor 尚未實作"


def create_live_exit_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_id: int,
) -> tuple[int | None, int | None, int | None, str]:
    """
    功能：LIVE 平倉骨架。
    回傳：
        (linked_order_id, closed_position_id, trade_id, guard_reason)
    """
    return None, None, None, "LIVE executor 尚未實作"