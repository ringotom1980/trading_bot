"""
Path: scripts/check_decision.py
說明：測試完整決策流程，抓取最新 K 線後計算 feature、signal，並在不同持倉情境下輸出 decision。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from strategy.decision import calculate_decision
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores


def main() -> None:
    """
    功能：決策流程測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_decision")

    settings = load_settings()
    client = BinanceClient(settings)

    logger.info("開始測試決策流程")
    logger.info("PRIMARY_SYMBOL=%s", settings.primary_symbol)
    logger.info("PRIMARY_INTERVAL=%s", settings.primary_interval)

    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=60,
    )

    feature_pack = calculate_feature_pack(
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        klines=klines,
    )

    signal_scores = calculate_signal_scores(feature_pack)

    long_score = signal_scores["long_score"]
    short_score = signal_scores["short_score"]

    logger.info("long_score=%s", long_score)
    logger.info("short_score=%s", short_score)

    no_position_decision = calculate_decision(
        long_score=long_score,
        short_score=short_score,
        current_position_side=None,
    )
    logger.info("NO_POSITION_DECISION=%s", no_position_decision)

    long_position_decision = calculate_decision(
        long_score=long_score,
        short_score=short_score,
        current_position_side="LONG",
    )
    logger.info("LONG_POSITION_DECISION=%s", long_position_decision)

    short_position_decision = calculate_decision(
        long_score=long_score,
        short_score=short_score,
        current_position_side="SHORT",
    )
    logger.info("SHORT_POSITION_DECISION=%s", short_position_decision)


if __name__ == "__main__":
    main()