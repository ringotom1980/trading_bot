"""
Path: scripts/check_market_data.py
說明：測試 Binance 市場資料是否可正常取得，並輸出最新 K 線摘要。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines


def main() -> None:
    """
    功能：市場資料測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_market_data")

    settings = load_settings()
    client = BinanceClient(settings)

    logger.info("開始測試市場資料")
    logger.info("目前 base_url=%s", client.base_url)
    logger.info("PRIMARY_SYMBOL=%s", settings.primary_symbol)
    logger.info("PRIMARY_INTERVAL=%s", settings.primary_interval)

    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=2,
    )

    logger.info("成功取得 K 線筆數：%s", len(klines))

    for index, kline in enumerate(klines, start=1):
        logger.info(
            "KLINE_%s | open_time=%s | close_time=%s | open=%s | high=%s | low=%s | close=%s | volume=%s",
            index,
            kline["open_time"],
            kline["close_time"],
            kline["open"],
            kline["high"],
            kline["low"],
            kline["close"],
            kline["volume"],
        )


if __name__ == "__main__":
    main()