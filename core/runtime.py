"""
Path: core/runtime.py
說明：即時執行流程骨架，負責讀取 system_state、更新 heartbeat，並依目前狀態決定是否進入交易流程。
"""

from __future__ import annotations

from psycopg2.extensions import connection as PgConnection

from config.logging import get_logger
from core.heartbeat import touch_system_heartbeat
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
    logger.info("目前 DB 狀態：engine_mode=%s, trade_mode=%s, trading_state=%s",
                system_state["engine_mode"],
                system_state["trade_mode"],
                system_state["trading_state"])

    # 每次 runtime 先更新心跳，表示系統仍存活
    touch_system_heartbeat(conn, state_id=1, updated_by="runtime_once")
    logger.info("已更新 system_state 心跳時間")

    # 第一版 runtime 骨架：先只判斷是否屬於即時交易模式
    if system_state["engine_mode"] != "REALTIME":
        logger.info("目前 engine_mode 不是 REALTIME，略過即時交易流程")
        return

    # 第一版 runtime 骨架：若交易狀態為 OFF，先不進交易流程
    if system_state["trading_state"] == "OFF":
        logger.info("目前 trading_state=OFF，暫不進入交易流程")
        return

    # 先保留骨架位置，下一包再接市場資料與決策流程
    logger.info("目前已符合基本 runtime 條件，下一步將接入市場資料與決策流程")