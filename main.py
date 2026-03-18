"""
Path: main.py
說明：主程式入口，負責載入設定、初始化 logging、連線資料庫，並讀取 system_state 與目前 ACTIVE 策略。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from services.strategy_service import load_active_strategy
from storage.db import connection_scope, test_connection
from storage.repositories.system_state_repo import get_system_state


def main() -> None:
    """
    功能：主程式啟動入口。
    """
    setup_logging()
    logger = get_logger("main")

    settings = load_settings()

    logger.info("trading_bot 啟動成功")
    logger.info("APP_ENV=%s", settings.app_env)
    logger.info("PRIMARY_SYMBOL=%s", settings.primary_symbol)
    logger.info("PRIMARY_INTERVAL=%s", settings.primary_interval)
    logger.info("ENGINE_MODE=%s", settings.engine_mode)
    logger.info("TRADE_MODE=%s", settings.trade_mode)
    logger.info("TRADING_STATE=%s", settings.trading_state)
    logger.info("LIVE_ARMED=%s", settings.live_armed)

    ok, message = test_connection()
    if not ok:
        logger.error(message)
        raise SystemExit(1)

    logger.info(message)

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)，請先執行 seed_strategy")

        active_strategy = load_active_strategy(conn)

    logger.info("SYSTEM_STATE_ID=%s", system_state["id"])
    logger.info("DB_ENGINE_MODE=%s", system_state["engine_mode"])
    logger.info("DB_TRADE_MODE=%s", system_state["trade_mode"])
    logger.info("DB_TRADING_STATE=%s", system_state["trading_state"])
    logger.info("DB_LIVE_ARMED=%s", system_state["live_armed"])
    logger.info("DB_ACTIVE_STRATEGY_VERSION_ID=%s", system_state["active_strategy_version_id"])

    logger.info("ACTIVE_STRATEGY_ID=%s", active_strategy["strategy_version_id"])
    logger.info("ACTIVE_VERSION_CODE=%s", active_strategy["version_code"])
    logger.info("ACTIVE_STATUS=%s", active_strategy["status"])
    logger.info("ACTIVE_SOURCE_TYPE=%s", active_strategy["source_type"])
    logger.info("ACTIVE_SYMBOL=%s", active_strategy["symbol"])
    logger.info("ACTIVE_INTERVAL=%s", active_strategy["interval"])


if __name__ == "__main__":
    main()