"""
Path: services/execution_service.py
說明：執行服務層，整合市場資料、特徵、訊號與決策，並在符合條件時建立模擬開倉或模擬平倉流程，同時避免同一根 bar 重複寫入 decision，並同步更新 system_state 的最後參照欄位。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from storage.repositories.decisions_repo import (
    get_decision_by_bar_close_time,
    insert_decision_log,
    mark_decision_executed,
)
from storage.repositories.orders_repo import create_order
from storage.repositories.positions_repo import (
    close_position,
    create_position,
    get_open_position_by_symbol,
    update_position_entry_order_id,
    update_position_exit_order_id,
)
from storage.repositories.system_state_repo import (
    update_current_position,
    update_runtime_refs,
)
from storage.repositories.trades_repo import create_trade_log
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

def _get_demo_safe_bar_times(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    latest_kline: dict[str, Any],
) -> tuple[datetime, datetime]:
    """
    功能：為 demo 強制交易流程產生可安全寫入 decisions_log 的 bar 時間。
    若同一根 bar_close_time 已存在 decision，則以微小位移避免撞唯一鍵。
    這只用於 demo force 流程，不影響正式 runtime。
    回傳：
        (bar_open_time, bar_close_time)
    """
    base_open_time = _ms_to_datetime(int(latest_kline["open_time"]))
    base_close_time = _ms_to_datetime(int(latest_kline["close_time"]))

    existing_decision = get_decision_by_bar_close_time(
        conn,
        symbol=symbol,
        interval=interval,
        bar_close_time=base_close_time,
    )

    if existing_decision is None:
        return base_open_time, base_close_time

    safe_open_time = base_open_time + timedelta(microseconds=1)
    safe_close_time = base_close_time + timedelta(microseconds=1)
    return safe_open_time, safe_close_time

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


def _create_simulated_exit_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
) -> tuple[int, int, int]:
    """
    功能：依目前 OPEN 持倉建立模擬平倉 order、關閉 position 並寫入 trades_log。
    回傳：
        (exit_order_id, closed_position_id, trade_id)
    """
    open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
    if open_position is None:
        raise RuntimeError("目前沒有 OPEN 持倉，無法執行模擬平倉流程")

    avg_price = float(latest_kline["close"])
    qty = float(open_position["entry_qty"])
    filled_at = _ms_to_datetime(int(latest_kline["close_time"]))

    if open_position["side"] == "LONG":
        order_side = "SELL"
        gross_pnl = (avg_price - float(open_position["entry_price"])) * qty
    else:
        order_side = "BUY"
        gross_pnl = (float(open_position["entry_price"]) - avg_price) * qty

    fees = 2.0
    net_pnl = gross_pnl - fees

    exit_order_id = create_order(
        conn,
        position_id=int(open_position["position_id"]),
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        engine_mode=system_state["engine_mode"],
        trade_mode=str(system_state["trade_mode"]),
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        client_order_id=f"runtime_exit_{int(latest_kline['close_time'])}",
        exchange_order_id=f"sim_exit_{int(latest_kline['close_time'])}",
        side=order_side,
        order_type="MARKET",
        reduce_only=True,
        qty=qty,
        price=None,
        avg_price=avg_price,
        status="FILLED",
        exchange_status_raw="FILLED",
        placed_at=filled_at,
        filled_at=filled_at,
        raw_request={
            "symbol": settings.primary_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": True,
        },
        raw_response={
            "status": "FILLED",
            "avgPrice": str(avg_price),
        },
    )

    update_position_exit_order_id(
        conn,
        position_id=int(open_position["position_id"]),
        exit_order_id=exit_order_id,
    )

    close_position(
        conn,
        position_id=int(open_position["position_id"]),
        exit_price=avg_price,
        exit_qty=qty,
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        closed_at=filled_at,
        close_reason="SIGNAL_EXIT",
    )

    trade_id = create_trade_log(
        conn,
        position_id=int(open_position["position_id"]),
        symbol=str(open_position["symbol"]),
        interval=str(open_position["interval"]),
        engine_mode=str(open_position["engine_mode"]),
        trade_mode=open_position["trade_mode"],
        strategy_version_id=int(open_position["strategy_version_id"]),
        side=str(open_position["side"]),
        entry_time=open_position["opened_at"],
        exit_time=filled_at,
        entry_price=float(open_position["entry_price"]),
        exit_price=avg_price,
        qty=qty,
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        bars_held=None,
        close_reason="SIGNAL_EXIT",
        entry_order_id=open_position["entry_order_id"],
        exit_order_id=exit_order_id,
    )

    update_current_position(
        conn,
        state_id=1,
        current_position_id=None,
        current_position_side=None,
        updated_by="runtime_exit_flow",
    )

    return exit_order_id, int(open_position["position_id"]), trade_id


def record_runtime_decision(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    client: BinanceClient,
) -> dict[str, Any]:
    """
    功能：由 runtime 整合市場資料、特徵、訊號與決策，寫入 decisions_log，並在 ENTER / EXIT 決策時建立模擬執行流程。
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

    target_bar_open_time = _ms_to_datetime(int(latest_kline["open_time"]))
    target_bar_close_time = _ms_to_datetime(int(latest_kline["close_time"]))

    existing_decision = get_decision_by_bar_close_time(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        bar_close_time=target_bar_close_time,
    )

    if existing_decision is not None:
        update_runtime_refs(
            conn,
            state_id=1,
            last_bar_close_time=target_bar_close_time,
            last_decision_id=existing_decision["decision_id"],
            last_order_id=existing_decision["linked_order_id"],
            last_trade_id=None,
            updated_by="runtime_skip_existing_decision",
        )

        return {
            "decision_id": existing_decision["decision_id"],
            "decision": existing_decision["decision"],
            "executed": existing_decision["executed"],
            "linked_order_id": existing_decision["linked_order_id"],
            "position_id_after": existing_decision["position_id_after"],
            "position_side_after": existing_decision["position_side_after"],
            "last_trade_id": None,
            "skipped": True,
        }

    decision_id = insert_decision_log(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        bar_open_time=target_bar_open_time,
        bar_close_time=target_bar_close_time,
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
    last_trade_id = None
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

    elif decision_result["decision"] == "EXIT" and system_state["current_position_id"] is not None:
        linked_order_id, _closed_position_id, last_trade_id = _create_simulated_exit_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
        )
        executed = True
        position_id_after = None
        position_side_after = None

    mark_decision_executed(
        conn,
        decision_id=decision_id,
        executed=executed,
        position_id_after=position_id_after,
        position_side_after=position_side_after,
        linked_order_id=linked_order_id,
    )

    update_runtime_refs(
        conn,
        state_id=1,
        last_bar_close_time=target_bar_close_time,
        last_decision_id=decision_id,
        last_order_id=linked_order_id,
        last_trade_id=last_trade_id,
        updated_by="record_runtime_decision",
    )

    return {
        "decision_id": decision_id,
        "decision": decision_result["decision"],
        "executed": executed,
        "linked_order_id": linked_order_id,
        "position_id_after": position_id_after,
        "position_side_after": position_side_after,
        "last_trade_id": last_trade_id,
        "skipped": False,
    }


def force_simulated_trade_cycle(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    client: BinanceClient,
    forced_decision: str,
) -> dict[str, Any]:
    """
    功能：強制執行模擬交易流程，供 demo 驗收用，不走策略訊號判斷。
    參數：
        forced_decision: 僅允許 ENTER_LONG、ENTER_SHORT、EXIT。
    回傳：
        執行結果摘要字典。
    """
    allowed_decisions = {"ENTER_LONG", "ENTER_SHORT", "EXIT"}
    if forced_decision not in allowed_decisions:
        raise ValueError(f"forced_decision 僅允許 {allowed_decisions}，收到：{forced_decision}")

    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=60,
    )
    latest_kline = klines[-1]
    target_bar_open_time, target_bar_close_time = _get_demo_safe_bar_times(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        latest_kline=latest_kline,
    )

    feature_pack = calculate_feature_pack(
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        klines=klines,
    )

    reason_map = {
        "ENTER_LONG": "demo force enter long",
        "ENTER_SHORT": "demo force enter short",
        "EXIT": "demo force exit",
    }

    decision_id = insert_decision_log(
        conn,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        bar_open_time=target_bar_open_time,
        bar_close_time=target_bar_close_time,
        engine_mode=system_state["engine_mode"],
        trade_mode=system_state["trade_mode"],
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        position_id_before=system_state["current_position_id"],
        position_side_before=system_state["current_position_side"],
        decision=forced_decision,
        decision_score=1.0,
        reason_code="MANUAL",
        reason_summary=reason_map[forced_decision],
        features=feature_pack,
        executed=False,
        position_id_after=None,
        position_side_after=system_state["current_position_side"],
        linked_order_id=None,
    )

    executed = False
    linked_order_id = None
    last_trade_id = None
    position_id_after = system_state["current_position_id"]
    position_side_after = system_state["current_position_side"]

    if forced_decision in {"ENTER_LONG", "ENTER_SHORT"}:
        if system_state["current_position_id"] is not None:
            raise RuntimeError("目前已有 OPEN 持倉，不能強制進場")

        linked_order_id, position_id_after, position_side_after = _create_simulated_entry_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_result={"decision": forced_decision},
        )
        executed = True

    elif forced_decision == "EXIT":
        if system_state["current_position_id"] is None:
            raise RuntimeError("目前沒有 OPEN 持倉，不能強制平倉")

        linked_order_id, _closed_position_id, last_trade_id = _create_simulated_exit_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
        )
        executed = True
        position_id_after = None
        position_side_after = None

    mark_decision_executed(
        conn,
        decision_id=decision_id,
        executed=executed,
        position_id_after=position_id_after,
        position_side_after=position_side_after,
        linked_order_id=linked_order_id,
    )

    update_runtime_refs(
        conn,
        state_id=1,
        last_bar_close_time=target_bar_close_time,
        last_decision_id=decision_id,
        last_order_id=linked_order_id,
        last_trade_id=last_trade_id,
        updated_by="force_simulated_trade_cycle",
    )

    return {
        "decision_id": decision_id,
        "decision": forced_decision,
        "executed": executed,
        "linked_order_id": linked_order_id,
        "position_id_after": position_id_after,
        "position_side_after": position_side_after,
        "last_trade_id": last_trade_id,
    }