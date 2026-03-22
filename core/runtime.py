"""
Path: core/runtime.py
說明：即時執行流程骨架，負責讀取 system_state、更新 heartbeat，透過守門模組判斷是否可進交易流程，並在通過時寫入 decisions_log 與執行流程。
"""

from __future__ import annotations

from time import sleep

from psycopg2.extensions import connection as PgConnection

from config.logging import get_logger
from config.settings import Settings
from core.guards import evaluate_runtime_guard
from core.heartbeat import touch_system_heartbeat
from core.state_machine import summarize_state
from exchange.binance_client import BinanceClient
from services.execution_service import record_runtime_decision
from services.strategy_service import load_active_strategy
from storage.repositories.system_events_repo import create_system_event
from storage.repositories.system_state_repo import get_system_state
from storage.db import connection_scope


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
        create_system_event(
            conn,
            event_type="GUARD_TRIGGERED",
            event_level="INFO",
            source="SYSTEM",
            message=reason,
            details={
                "guard_type": "runtime_guard",
                "symbol": settings.primary_symbol,
                "interval": settings.primary_interval,
                "state_summary": summarize_state(system_state),
            },
            created_by="run_runtime_once",
            engine_mode_before=system_state["engine_mode"],
            engine_mode_after=system_state["engine_mode"],
            trade_mode_before=system_state["trade_mode"],
            trade_mode_after=system_state["trade_mode"],
            trading_state_before=system_state["trading_state"],
            trading_state_after=system_state["trading_state"],
            live_armed_before=system_state["live_armed"],
            live_armed_after=system_state["live_armed"],
            strategy_version_before=system_state["active_strategy_version_id"],
            strategy_version_after=system_state["active_strategy_version_id"],
        )
        logger.info(reason)
        return

    logger.info(reason)

    client = BinanceClient(settings)

    result = record_runtime_decision(
        conn,
        settings=settings,
        system_state=system_state,
        active_strategy=active_strategy,
        client=client,
    )

    if result.get("skipped"):
        logger.info(
            "同一根 bar 的 decision 已存在，略過重複寫入：decision_id=%s, decision=%s, executed=%s",
            result["decision_id"],
            result["decision"],
            result["executed"],
        )
        return

    logger.info(
        "runtime 決策完成：decision_id=%s, decision=%s, executed=%s, linked_order_id=%s, position_id_after=%s, position_side_after=%s",
        result["decision_id"],
        result["decision"],
        result["executed"],
        result["linked_order_id"],
        result["position_id_after"],
        result["position_side_after"],
    )


def run_runtime_loop(
    *,
    settings: Settings,
    poll_interval_seconds: int = 5,
) -> None:
    """
    功能：以前景常駐模式持續執行 runtime。
    說明：
        - 每輪重新開一個 connection_scope，避免長交易不 commit。
        - 每輪重新載入 ACTIVE 策略，避免後續升版後仍使用舊策略。
        - 每輪呼叫 run_runtime_once()。
        - 若單輪失敗，記錄 log 後不中斷整體迴圈。
    參數：
        settings: 全域設定物件。
        poll_interval_seconds: 輪詢秒數。
    """
    logger = get_logger("core.runtime")
    logger.info("runtime loop 啟動，poll_interval_seconds=%s", poll_interval_seconds)

    while True:
        try:
            with connection_scope() as conn:
                active_strategy = load_active_strategy(conn)

                run_runtime_once(
                    conn,
                    settings=settings,
                    active_strategy=active_strategy,
                )

        except KeyboardInterrupt:
            logger.info("收到 KeyboardInterrupt，結束 runtime loop")
            raise

        except Exception as exc:
            logger.exception("runtime loop 單輪執行失敗：%s", exc)

        sleep(poll_interval_seconds)