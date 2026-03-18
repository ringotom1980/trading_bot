"""
Path: core/runtime.py
說明：即時執行流程骨架，負責讀取 system_state、更新 heartbeat，並透過狀態機與守門模組決定是否進入交易流程。
"""

from __future__ import annotations

from psycopg2.extensions import connection as PgConnection

from config.logging import get_logger
from core.guards import evaluate_runtime_guard
from core.heartbeat import touch_system_heartbeat
from core.state_machine import summarize_state
from storage.repositories.system_state_repo import get_system_state


def run_runtime_once(conn: PgConnection) -> None:
    """
    功能：執行一次最小 runtime 流程。
    參數：
        conn: PostgreSQL 連線物件。
    """
    logger = get_logger("core.runtime")

    system_state = get_system_state(conn, 1)
    if system_state is None:
        raise RuntimeError("找不到 system_state(id=1)，無法執行 runtime")

    logger.info("開始執行 runtime 一次流程")
    logger.info("目前 DB 狀態摘要：%s", summarize_state(system_state))

    # 每次 runtime 先更新心跳，表示系統仍存活
    touch_system_heartbeat(conn, state_id=1, updated_by="runtime_once")
    logger.info("已更新 system_state 心跳時間")

    allowed, reason = evaluate_runtime_guard(system_state)
    if not allowed:
        logger.info(reason)
        return

    logger.info(reason)
    logger.info("目前已通過 runtime 守門條件，下一步將接入市場資料與決策流程")