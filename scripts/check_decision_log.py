"""
Path: scripts/check_decision_log.py
說明：測試 decision 寫入流程，抓取市場資料、計算 feature 與 decision，並將結果寫入 decisions_log。
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from storage.db import connection_scope
from storage.repositories.decisions_repo import get_latest_decision_log, insert_decision_log
from storage.repositories.system_state_repo import get_system_state
from strategy.decision import calculate_decision
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores


def ms_to_datetime(ms: int) -> datetime:
    """
    功能：將毫秒時間戳轉為 UTC datetime。
    """
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def main() -> None:
    """
    功能：decision 寫入測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_decision_log")

    settings = load_settings()
    client = BinanceClient(settings)

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

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        decision_result = calculate_decision(
            long_score=signal_scores["long_score"],
            short_score=signal_scores["short_score"],
            current_position_side=system_state["current_position_side"],
        )

        latest_kline = klines[-1]
        decision_id = insert_decision_log(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            bar_open_time=ms_to_datetime(int(latest_kline["open_time"])),
            bar_close_time=ms_to_datetime(int(latest_kline["close_time"])),
            engine_mode=system_state["engine_mode"],
            trade_mode=system_state["trade_mode"],
            strategy_version_id=int(system_state["active_strategy_version_id"]),
            position_id_before=system_state["current_position_id"],
            position_side_before=system_state["current_position_side"],
            decision=decision_result["decision"],
            decision_score=float(decision_result["decision_score"]),
            reason_code=decision_result["reason_code"],
            reason_summary=decision_result["reason_summary"],
            features=feature_pack,
            executed=False,
        )

        latest_decision = get_latest_decision_log(conn)

    logger.info("已寫入 decisions_log，decision_id=%s", decision_id)
    logger.info("LATEST_DECISION=%s", latest_decision)
if __name__ == "__main__":
    main()