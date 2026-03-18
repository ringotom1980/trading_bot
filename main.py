"""
Path: main.py
說明：主程式入口，負責載入設定、初始化 logging，並輸出目前系統啟動基本資訊。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings


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


if __name__ == "__main__":
    main()