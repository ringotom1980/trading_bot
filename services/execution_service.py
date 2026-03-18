"""
Path: services/execution_service.py
說明：執行服務層，先負責將市場資料、特徵、訊號與決策整合後寫入 decisions_log，暫不進行真實下單。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from storage.repositories.decisions_repo import insert_decision_log
from strategy.decision import calculate_decision
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores


def _ms_to_datetime(ms: int) -> datetime:
    """
    功能：將毫秒時間戳轉為 UTC datetime。
    參數：
        ms: 毫秒時間戳。
    回傳：
        帶時區的 datetime 物件。
    """
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def build_decision_context(
    settings: Settings,
    client: BinanceClient,
    current_position_side: str | None,
) -> dict[str, Any]:
    """
    功能：抓取市場資料並計算 feature、signal 與 decision。
    參數：
        settings: 全域設定物件。
        client: Binance API 客戶端。
        current_position_side: 目前持倉方向。
    回傳：
        包含 klines、feature_pack、signal_scores、decision_result 的整合字典。
    """
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

    decision_result = calculate_decision(
        long_score=signal_scores["long_score"],
        short_score=signal_scores["short_score"],
        current_position_side=current_position_side,
    )

    return {
        "klines": klines,
        "feature_pack": feature_pack,
        "signal_scores": signal_scores,
        "decision_result": decision_result,
    }


def record_runtime_decision(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    client: BinanceClient,
) -> int:
    """
    功能：由 runtime 整合市場資料、特徵、訊號與決策，並寫入 decisions_log。
    參數：
        conn: PostgreSQL 連線物件。
        settings: 全域設定物件。
        system_state: system_state 資料字典。
        active_strategy: ACTIVE 策略資料字典。
        client: Binance API 客戶端。
    回傳：
        新建立的 decision_id。
    """
    context = build_decision_context(
        settings=settings,
        client=client,
        current_position_side=system_state["current_position_side"],
    )

    latest_kline = context["klines"][-1]
    feature_pack = context["feature_pack"]
    decision_result = context["decision_result"]

    decision_id = insert_decision_log(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        bar_open_time=_ms_to_datetime(int(latest_kline["open_time"])),
        bar_close_time=_ms_to_datetime(int(latest_kline["close_time"])),
        engine_mode=system_state["engine_mode"],
        trade_mode=system_state["trade_mode"],
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        position_id_before=system_state["current_position_id"],
        position_side_before=system_state["current_position_side"],
        decision=decision_result["decision"],
        decision_score=float(decision_result["decision_score"]),
        reason_code=decision_result["reason_code"],
        reason_summary=decision_result["reason_summary"],
        features=feature_pack,
        executed=False,
        position_id_after=None,
        position_side_after=system_state["current_position_side"],
        linked_order_id=None,
    )

    return decision_id