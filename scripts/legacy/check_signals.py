"""
Path: scripts/check_signals.py
說明：測試訊號評分流程，抓取最新 K 線後計算 feature pack 與 long/short 分數。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores


def main() -> None:
    """
    功能：訊號評分測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_signals")

    settings = load_settings()
    client = BinanceClient(settings)

    logger.info("開始測試訊號評分")
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

    signal_scores = calculate_signal_scores(feature_pack)

    logger.info("feature 計算完成")
    logger.info("bar_close_time=%s", feature_pack["bar_close_time"])
    logger.info("rsi_14=%s", feature_pack["rsi_14"])
    logger.info("macd_hist=%s", feature_pack["macd_hist"])
    logger.info("kd_diff=%s", feature_pack["kd_diff"])
    logger.info("close_vs_sma20_pct=%s", feature_pack["close_vs_sma20_pct"])
    logger.info("close_vs_sma60_pct=%s", feature_pack["close_vs_sma60_pct"])
    logger.info("slope_5=%s", feature_pack["slope_5"])
    logger.info("slope_10=%s", feature_pack["slope_10"])
    logger.info("atr_14_pct=%s", feature_pack["atr_14_pct"])
    logger.info("volatility_10=%s", feature_pack["volatility_10"])
    logger.info("volume_ratio_20=%s", feature_pack["volume_ratio_20"])
    logger.info("volume_slope_5=%s", feature_pack["volume_slope_5"])
    logger.info("regime=%s", feature_pack["regime"])
    logger.info("regime_score=%s", feature_pack["regime_score"])

    logger.info("signal 計算完成")
    logger.info("long_score=%s", signal_scores["long_score"])
    logger.info("short_score=%s", signal_scores["short_score"])


if __name__ == "__main__":
    main()