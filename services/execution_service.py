"""
Path: services/execution_service.py
說明：執行服務層，整合市場資料、特徵、訊號與決策，並在符合條件時建立模擬 order 與 position。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from storage.repositories.decisions_repo import insert_decision_log, mark_decision_executed
from storage.repositories.orders_repo import create_order
from storage.repositories.positions_repo import create_position, update_position_entry_order_id
from storage.repositories.system_state_repo import update_current_position
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


def _create_simulated_entry_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_result: dict[str, Any],
) -> tuple[int, int, str]:
    """
    功能：依 ENTER_LONG / ENTER_SHORT 建立模擬開倉 order 與 position。
    參數：
        conn: PostgreSQL 連線物件。
        settings: 全域設定物件。
        system_state: system_state 資料字典。
        active_strategy: ACTIVE 策略資料字典。
        latest_kline: 最新 K 線資料。
        decision_result: 決策結果。
    回傳：
        (order_id, position_id, position_side)
    """
    decision = str(decision_result["decision"])
    avg_price = float(latest_kline["close"])
    qty = 0.01
    placed_at = _ms_to_datetime(int(latest_kline["close_time"]))

    if decision == "ENTER_LONG":
        order_side = "BUY"
        position_side = "LONG"
    elif decision == "ENTER_SHORT":
        order_side = "SELL"
        position_side = "SHORT"
    else:
        raise ValueError(f"不支援的進場決策：{decision}")

    order_id = create_order(
        conn,
        position_id=None,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=str(system_state["trade_mode"]),
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        client_order_id=f"runtime_{decision.lower()}_{int(latest_kline['close_time'])}",
        exchange_order_id=f"sim_{decision.lower()}_{int(latest_kline['close_time'])}",
        side=order_side,
        order_type="MARKET",
        reduce_only=False,
        qty=qty,
        price=None,
        avg_price=avg_price,
        status="FILLED",
        exchange_status_raw="FILLED",
        placed_at=placed_at,
        filled_at=placed_at,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
        },
        raw_response={
            "status": "FILLED",
            "avgPrice": str(avg_price),
        },
    )

    entry_notional = avg_price * qty

    position_id = create_position(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=system_state["trade_mode"],
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        side=position_side,
        entry_price=avg_price,
        entry_qty=qty,
        entry_notional=entry_notional,
        opened_at=placed_at,
        exchange_position_ref=None,
    )

    update_position_entry_order_id(
        conn,
        position_id=position_id,
        entry_order_id=order_id,
    )

    update_current_position(
        conn,
        state_id=1,
        current_position_id=position_id,
        current_position_side=position_side,
        updated_by="runtime_entry_flow",
    )

    return order_id, position_id, position_side


def record_runtime_decision(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    client: BinanceClient,
) -> dict[str, Any]:
    """
    功能：由 runtime 整合市場資料、特徵、訊號與決策，寫入 decisions_log，並在 ENTER 決策時建立模擬開倉流程。
    參數：
        conn: PostgreSQL 連線物件。
        settings: 全域設定物件。
        system_state: system_state 資料字典。
        active_strategy: ACTIVE 策略資料字典。
        client: Binance API 客戶端。
    回傳：
        執行結果摘要字典。
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

    executed = False
    linked_order_id = None
    position_id_after = None
    position_side_after = system_state["current_position_side"]

    if decision_result["decision"] in {"ENTER_LONG", "ENTER_SHORT"} and system_state["current_position_id"] is None:
        linked_order_id, position_id_after, position_side_after = _create_simulated_entry_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_result=decision_result,
        )
        executed = True

    mark_decision_executed(
        conn,
        decision_id=decision_id,
        executed=executed,
        position_id_after=position_id_after,
        position_side_after=position_side_after,
        linked_order_id=linked_order_id,
    )

    return {
        "decision_id": decision_id,
        "decision": decision_result["decision"],
        "executed": executed,
        "linked_order_id": linked_order_id,
        "position_id_after": position_id_after,
        "position_side_after": position_side_after,
    }