"""
Path: core/runtime.py
說明：即時執行流程骨架，負責讀取 system_state、更新 heartbeat，透過守門模組判斷是否可進交易流程，並在通過時寫入 decisions_log。
"""

from __future__ import annotations

from psycopg2.extensions import connection as PgConnection

from config.logging import get_logger
from config.settings import Settings
from core.guards import evaluate_runtime_guard
from core.heartbeat import touch_system_heartbeat
from core.state_machine import summarize_state
from exchange.binance_client import BinanceClient
from services.execution_service import record_runtime_decision
from storage.repositories.system_state_repo import get_system_state


def run_runtime_once(
    conn: PgConnection,
    *,
    settings: Settings,
    active_strategy: dict,
) -> None:
    """
    功能：執行一次最小 runtime 流程。
    參數：
        conn: PostgreSQL 連線物件。
        settings: 全域設定物件。
        active_strategy: 目前 ACTIVE 策略資料字典。
    """
    logger = get_logger("core.runtime")

    system_state = get_system_state(conn, 1)
    if system_state is None:
        raise RuntimeError("找不到 system_state(id=1)，無法執行 runtime")

    logger.info("開始執行 runtime 一次流程")
    logger.info("目前 DB 狀態摘要：%s", summarize_state(system_state))

    touch_system_heartbeat(conn, state_id=1, updated_by="runtime_once")
    logger.info("已更新 system_state 心跳時間")

    allowed, reason = evaluate_runtime_guard(system_state)
    if not allowed:
        logger.info(reason)
        return

    logger.info(reason)

    client = BinanceClient(settings)

    decision_id = record_runtime_decision(
        conn,
        settings=settings,
        system_state=system_state,
        active_strategy=active_strategy,
        client=client,
    )

    logger.info("已由 runtime 寫入 decisions_log，decision_id=%s", decision_id)