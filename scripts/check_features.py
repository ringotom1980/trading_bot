"""
Path: scripts/check_features.py
說明：測試特徵計算流程，抓取最新 K 線後計算第一版 feature pack 並輸出結果。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from strategy.features import calculate_feature_pack


def main() -> None:
    """
    功能：特徵計算測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_features")

    settings = load_settings()
    client = BinanceClient(settings)

    logger.info("開始測試特徵計算")
    logger.info("PRIMARY_SYMBOL=%s", settings.primary_symbol)
    logger.info("PRIMARY_INTERVAL=%s", settings.primary_interval)

    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=60,
    )

    logger.info("成功取得 K 線筆數：%s", len(klines))

    feature_pack = calculate_feature_pack(
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        klines=klines,
    )

    logger.info("特徵計算完成")
    logger.info("bar_close_time=%s", feature_pack["bar_close_time"])
    logger.info("close_vs_sma20_pct=%s", feature_pack["close_vs_sma20_pct"])
    logger.info("close_vs_sma60_pct=%s", feature_pack["close_vs_sma60_pct"])
    logger.info("slope_5=%s", feature_pack["slope_5"])
    logger.info("slope_10=%s", feature_pack["slope_10"])
    logger.info("range_pct=%s", feature_pack["range_pct"])
    logger.info("volatility_10=%s", feature_pack["volatility_10"])
    logger.info("volume_ratio_20=%s", feature_pack["volume_ratio_20"])
    logger.info("volume_slope_5=%s", feature_pack["volume_slope_5"])


if __name__ == "__main__":
    main()