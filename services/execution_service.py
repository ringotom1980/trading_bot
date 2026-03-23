"""
Path: services/execution_service.py
說明：執行服務層，負責整合市場資料、特徵、訊號與決策，並依 trade_mode 分流到 simulated / live executor，同時避免同一根 bar 重複寫入 decision，並同步更新 system_state 的最後參照欄位。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2.extensions import connection as PgConnection

from config.settings import Settings
from config.logging import get_logger
from core.guards import (
    evaluate_cooldown_guard,
    evaluate_entry_guard,
    evaluate_exit_guard,
    evaluate_runtime_guard,
)
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from services.executors.live_executor import (
    create_live_entry_flow,
    create_live_exit_flow,
)
from services.executors.simulated_executor import (
    create_simulated_entry_flow,
    create_simulated_exit_flow,
)
from config.constants import (
    TRADE_MODE_SIMULATION,
    TRADE_MODE_TESTNET,
    TRADE_MODE_LIVE,
)
from storage.repositories.decisions_repo import (
    get_decision_by_bar_close_time,
    insert_decision_log,
    mark_decision_executed,
)
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.system_events_repo import create_system_event
from storage.repositories.system_state_repo import update_runtime_refs
from storage.repositories.trades_repo import get_latest_closed_trade_by_symbol
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


def _calculate_unrealized_pnl_pct(
    *,
    side: str,
    entry_price: float,
    current_price: float,
) -> float:
    """
    功能：計算未實現報酬率（正數=浮盈，負數=浮虧）。
    """
    if entry_price <= 0:
        return 0.0

    if side == "LONG":
        return (current_price - entry_price) / entry_price

    if side == "SHORT":
        return (entry_price - current_price) / entry_price

    raise ValueError(f"不支援的持倉方向：{side}")


def _calculate_held_bars(
    *,
    opened_at: datetime,
    current_bar_close_time: datetime,
    bar_minutes: int,
) -> int:
    """
    功能：計算目前持倉已持有幾根 bar。
    """
    if current_bar_close_time <= opened_at:
        return 0

    hold_seconds = (current_bar_close_time - opened_at).total_seconds()
    return int(hold_seconds // (bar_minutes * 60))


def _evaluate_position_risk_exit(
    *,
    open_position: dict[str, Any] | None,
    latest_kline: dict[str, Any],
    current_bar_close_time: datetime,
    params: dict[str, Any] | None,
    bar_minutes: int = 15,
) -> dict[str, Any] | None:
    """
    功能：持倉中先檢查風控是否應強制 EXIT。
    回傳：
        若觸發則回傳 decision_result 格式；否則回傳 None。
    """
    if open_position is None or not params:
        return None

    hard_stop_loss_pct = float(params.get("hard_stop_loss_pct", 0.0) or 0.0)
    take_profit_pct = float(params.get("take_profit_pct", 0.0) or 0.0)
    max_bars_hold = int(params.get("max_bars_hold", 0) or 0)

    current_price = float(latest_kline["close"])
    entry_price = float(open_position["entry_price"])
    side = str(open_position["side"])
    opened_at = open_position["opened_at"]

    pnl_pct = _calculate_unrealized_pnl_pct(
        side=side,
        entry_price=entry_price,
        current_price=current_price,
    )

    if hard_stop_loss_pct > 0 and pnl_pct <= -hard_stop_loss_pct:
        return {
            "decision": "EXIT",
            "decision_score": abs(pnl_pct),
            "reason_code": "HARD_STOP_LOSS",
            "reason_summary": (
                f"觸發固定停損：pnl_pct={pnl_pct:.6f} <= -{hard_stop_loss_pct:.6f}"
            ),
        }

    if take_profit_pct > 0 and pnl_pct >= take_profit_pct:
        return {
            "decision": "EXIT",
            "decision_score": pnl_pct,
            "reason_code": "TAKE_PROFIT",
            "reason_summary": (
                f"觸發固定停利：pnl_pct={pnl_pct:.6f} >= {take_profit_pct:.6f}"
            ),
        }

    if max_bars_hold > 0 and opened_at is not None:
        held_bars = _calculate_held_bars(
            opened_at=opened_at,
            current_bar_close_time=current_bar_close_time,
            bar_minutes=bar_minutes,
        )
        if held_bars >= max_bars_hold:
            return {
                "decision": "EXIT",
                "decision_score": float(held_bars),
                "reason_code": "MAX_HOLD_BARS",
                "reason_summary": (
                    f"觸發最長持倉限制：held_bars={held_bars} >= max_bars_hold={max_bars_hold}"
                ),
            }

    return None


def build_decision_context(
    settings: Settings,
    client: BinanceClient,
    current_position_side: str | None,
    strategy_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    功能：抓取市場資料並計算 feature、signal 與 decision。
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

    signal_scores = calculate_signal_scores(feature_pack, strategy_params)
    
    decision_result = calculate_decision(
        long_score=signal_scores["long_score"],
        short_score=signal_scores["short_score"],
        current_position_side=current_position_side,
        params=strategy_params,
    )

    return {
        "klines": klines,
        "feature_pack": feature_pack,
        "signal_scores": signal_scores,
        "decision_result": decision_result,
    }


def execute_entry_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_result: dict[str, Any],
    decision_id: int,
) -> tuple[bool, int | None, int | None, str | None, str | None]:
    """
    功能：依 trade_mode 分流進場執行器。
    回傳：
        (executed, linked_order_id, position_id_after, position_side_after, guard_reason)
    """
    trade_mode = str(system_state["trade_mode"])

    if trade_mode == TRADE_MODE_SIMULATION:
        linked_order_id, position_id_after, position_side_after = create_simulated_entry_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_result=decision_result,
            decision_id=decision_id,
        )
        return True, linked_order_id, position_id_after, position_side_after, None

    if trade_mode in {TRADE_MODE_TESTNET, TRADE_MODE_LIVE}:
        linked_order_id, position_id_after, position_side_after, guard_reason = create_live_entry_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_result=decision_result,
            decision_id=decision_id,
        )
        executed = (
            guard_reason is None
            and linked_order_id is not None
            and position_id_after is not None
            and position_side_after is not None
        )
        return executed, linked_order_id, position_id_after, position_side_after, guard_reason

    return False, None, None, None, f"不支援的 trade_mode：{trade_mode}"


def execute_exit_flow(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    latest_kline: dict[str, Any],
    decision_id: int,
) -> tuple[bool, int | None, int | None, str | None]:
    """
    功能：依 trade_mode 分流平倉執行器。
    回傳：
        (executed, linked_order_id, last_trade_id, guard_reason)
    """
    trade_mode = str(system_state["trade_mode"])

    if trade_mode == TRADE_MODE_SIMULATION:
        linked_order_id, _closed_position_id, last_trade_id = create_simulated_exit_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_id=decision_id,
        )
        return True, linked_order_id, last_trade_id, None

    if trade_mode in {TRADE_MODE_TESTNET, TRADE_MODE_LIVE}:
        linked_order_id, _closed_position_id, last_trade_id, guard_reason = create_live_exit_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_id=decision_id,
        )
        executed = (
            guard_reason is None
            and linked_order_id is not None
        )
        return executed, linked_order_id, last_trade_id, guard_reason

    return False, None, None, f"不支援的 trade_mode：{trade_mode}"


def record_runtime_decision(
    conn: PgConnection,
    *,
    settings: Settings,
    system_state: dict[str, Any],
    active_strategy: dict[str, Any],
    client: BinanceClient,
) -> dict[str, Any]:
    """
    功能：由 runtime 整合市場資料、特徵、訊號與決策，寫入 decisions_log，並在 ENTER / EXIT 決策時建立執行流程。
    """
    logger = get_logger("services.execution_service")

    context = build_decision_context(
        settings=settings,
        client=client,
        current_position_side=system_state["current_position_side"],
        strategy_params=dict(active_strategy["params_json"] or {}),
    )

    latest_kline = context["klines"][-1]
    feature_pack = context["feature_pack"]
    signal_scores = context["signal_scores"]
    decision_result = context["decision_result"]

    params = active_strategy["params_json"]
    entry_threshold = float(params.get("entry_threshold", 0.0))
    exit_threshold = float(params.get("exit_threshold", 0.0))
    reverse_threshold = float(params.get("reverse_threshold", 0.0))
    reverse_gap = float(params.get("reverse_gap", 0.0))

    logger.info(
        "策略分數：long_score=%.6f, short_score=%.6f, entry_threshold=%.6f, exit_threshold=%.6f, reverse_threshold=%.6f, reverse_gap=%.6f, decision=%s",
        float(signal_scores["long_score"]),
        float(signal_scores["short_score"]),
        entry_threshold,
        exit_threshold,
        reverse_threshold,
        reverse_gap,
        decision_result["decision"],
    )

    target_bar_open_time = _ms_to_datetime(int(latest_kline["open_time"]))
    target_bar_close_time = _ms_to_datetime(int(latest_kline["close_time"]))
    
    open_position = get_open_position_by_symbol(conn, settings.primary_symbol)

    risk_exit_decision = _evaluate_position_risk_exit(
        open_position=open_position,
        latest_kline=latest_kline,
        current_bar_close_time=target_bar_close_time,
        params=dict(active_strategy["params_json"] or {}),
        bar_minutes=15,
    )

    if risk_exit_decision is not None:
        logger.info(
            "風控覆寫策略 decision：original_decision=%s, risk_decision=%s, reason_code=%s, reason_summary=%s",
            decision_result["decision"],
            risk_exit_decision["decision"],
            risk_exit_decision["reason_code"],
            risk_exit_decision["reason_summary"],
        )
        decision_result = {
            **decision_result,
            **risk_exit_decision,
        }

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

        create_system_event(
            conn,
            event_type="GUARD_TRIGGERED",
            event_level="INFO",
            source="SYSTEM",
            message="同一根 bar 的 decision 已存在，略過重複寫入",
            details={
                "symbol": settings.primary_symbol,
                "interval": settings.primary_interval,
                "decision_id": existing_decision["decision_id"],
                "decision": existing_decision["decision"],
                "bar_close_time": target_bar_close_time.isoformat(),
            },
            created_by="record_runtime_decision",
            engine_mode_before=system_state["engine_mode"],
            engine_mode_after=system_state["engine_mode"],
            trade_mode_before=system_state["trade_mode"],
            trade_mode_after=system_state["trade_mode"],
            trading_state_before=system_state["trading_state"],
            trading_state_after=system_state["trading_state"],
            live_armed_before=system_state["live_armed"],
            live_armed_after=system_state["live_armed"],
            strategy_version_before=system_state["active_strategy_version_id"],
            strategy_version_after=system_state["active_strategy_version_id"],
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

    create_system_event(
        conn,
        event_type="DECISION_RECORDED",
        event_level="INFO",
        source="SYSTEM",
        message=f"runtime decision 已寫入：{decision_result['decision']}",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "interval": settings.primary_interval,
            "decision": decision_result["decision"],
            "bar_close_time": target_bar_close_time.isoformat(),
            "position_id_before": system_state["current_position_id"],
            "position_side_before": system_state["current_position_side"],
        },
        created_by="record_runtime_decision",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    executed = False
    linked_order_id = None
    last_trade_id = None
    position_id_after = None
    position_side_after = system_state["current_position_side"]
    guard_reason = None
    min_hold_bars = int(active_strategy["params_json"].get("min_hold_bars", 0))
    cooldown_bars = int(active_strategy["params_json"].get("cooldown_bars", 0))

    if decision_result["decision"] in {"ENTER_LONG", "ENTER_SHORT"}:
        allow_entry, guard_reason = evaluate_entry_guard(system_state)

        if allow_entry:
            latest_closed_trade = get_latest_closed_trade_by_symbol(
                conn, settings.primary_symbol
            )
            allow_cooldown, cooldown_reason = evaluate_cooldown_guard(
                latest_closed_trade=latest_closed_trade,
                current_bar_close_time=target_bar_close_time,
                cooldown_bars=cooldown_bars,
                bar_minutes=15,
            )

            if allow_cooldown:
                executed, linked_order_id, position_id_after, position_side_after, guard_reason = execute_entry_flow(
                    conn,
                    settings=settings,
                    system_state=system_state,
                    active_strategy=active_strategy,
                    latest_kline=latest_kline,
                    decision_result=decision_result,
                    decision_id=decision_id,
                )
            else:
                guard_reason = cooldown_reason

    elif decision_result["decision"] == "EXIT":

        allow_exit, guard_reason = evaluate_exit_guard(
            system_state,
            open_position=open_position,
            current_bar_close_time=target_bar_close_time,
            min_hold_bars=min_hold_bars,
        )

        if allow_exit:
            executed, linked_order_id, last_trade_id, guard_reason = execute_exit_flow(
                conn,
                settings=settings,
                system_state=system_state,
                active_strategy=active_strategy,
                latest_kline=latest_kline,
                decision_id=decision_id,
            )
            if executed:
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

    if not executed and guard_reason:
        create_system_event(
            conn,
            event_type="GUARD_TRIGGERED",
            event_level="INFO",
            source="SYSTEM",
            message=guard_reason,
            details={
                "decision_id": decision_id,
                "decision": decision_result["decision"],
                "symbol": settings.primary_symbol,
                "interval": settings.primary_interval,
                "bar_close_time": target_bar_close_time.isoformat(),
            },
            created_by="record_runtime_decision",
            engine_mode_before=system_state["engine_mode"],
            engine_mode_after=system_state["engine_mode"],
            trade_mode_before=system_state["trade_mode"],
            trade_mode_after=system_state["trade_mode"],
            trading_state_before=system_state["trading_state"],
            trading_state_after=system_state["trading_state"],
            live_armed_before=system_state["live_armed"],
            live_armed_after=system_state["live_armed"],
            strategy_version_before=system_state["active_strategy_version_id"],
            strategy_version_after=system_state["active_strategy_version_id"],
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
    """
    allowed_decisions = {"ENTER_LONG", "ENTER_SHORT", "EXIT"}
    if forced_decision not in allowed_decisions:
        raise ValueError(
            f"forced_decision 僅允許 {allowed_decisions}，收到：{forced_decision}"
        )

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

    create_system_event(
        conn,
        event_type="DECISION_RECORDED",
        event_level="INFO",
        source="MANUAL",
        message=f"demo force decision 已寫入：{forced_decision}",
        details={
            "decision_id": decision_id,
            "symbol": settings.primary_symbol,
            "interval": settings.primary_interval,
            "decision": forced_decision,
            "bar_close_time": target_bar_close_time.isoformat(),
            "position_id_before": system_state["current_position_id"],
            "position_side_before": system_state["current_position_side"],
        },
        created_by="demo_force_trade_cycle",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
    )

    allow_runtime, runtime_reason = evaluate_runtime_guard(system_state)
    if not allow_runtime:
        create_system_event(
            conn,
            event_type="GUARD_TRIGGERED",
            event_level="INFO",
            source="MANUAL",
            message=runtime_reason,
            details={
                "decision_id": decision_id,
                "forced_decision": forced_decision,
                "symbol": settings.primary_symbol,
                "interval": settings.primary_interval,
                "bar_close_time": target_bar_close_time.isoformat(),
            },
            created_by="demo_force_trade_cycle",
            engine_mode_before=system_state["engine_mode"],
            engine_mode_after=system_state["engine_mode"],
            trade_mode_before=system_state["trade_mode"],
            trade_mode_after=system_state["trade_mode"],
            trading_state_before=system_state["trading_state"],
            trading_state_after=system_state["trading_state"],
            live_armed_before=system_state["live_armed"],
            live_armed_after=system_state["live_armed"],
            strategy_version_before=system_state["active_strategy_version_id"],
            strategy_version_after=system_state["active_strategy_version_id"],
        )

        update_runtime_refs(
            conn,
            state_id=1,
            last_bar_close_time=target_bar_close_time,
            last_decision_id=decision_id,
            last_order_id=None,
            last_trade_id=None,
            updated_by="force_simulated_trade_cycle",
        )

        return {
            "decision_id": decision_id,
            "decision": forced_decision,
            "executed": False,
            "linked_order_id": None,
            "position_id_after": system_state["current_position_id"],
            "position_side_after": system_state["current_position_side"],
            "last_trade_id": None,
            "blocked": True,
            "reason": runtime_reason,
        }

    executed = False
    linked_order_id = None
    last_trade_id = None
    position_id_after = system_state["current_position_id"]
    position_side_after = system_state["current_position_side"]

    if forced_decision in {"ENTER_LONG", "ENTER_SHORT"}:
        if system_state["current_position_id"] is not None:
            raise RuntimeError("目前已有 OPEN 持倉，不能強制進場")

        linked_order_id, position_id_after, position_side_after = create_simulated_entry_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_result={"decision": forced_decision},
            decision_id=decision_id,
        )
        executed = True

    elif forced_decision == "EXIT":
        if system_state["current_position_id"] is None:
            raise RuntimeError("目前沒有 OPEN 持倉，不能強制平倉")

        linked_order_id, _closed_position_id, last_trade_id = create_simulated_exit_flow(
            conn,
            settings=settings,
            system_state=system_state,
            active_strategy=active_strategy,
            latest_kline=latest_kline,
            decision_id=decision_id,
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

    create_system_event(
        conn,
        event_type="MANUAL_ACTION",
        event_level="INFO",
        source="MANUAL",
        message=f"demo force trade 執行：{forced_decision}",
        details={
            "decision_id": decision_id,
            "forced_decision": forced_decision,
            "linked_order_id": linked_order_id,
            "position_id_after": position_id_after,
            "position_side_after": position_side_after,
            "last_trade_id": last_trade_id,
            "bar_close_time": target_bar_close_time.isoformat(),
        },
        created_by="demo_force_trade_cycle",
        engine_mode_before=system_state["engine_mode"],
        engine_mode_after=system_state["engine_mode"],
        trade_mode_before=system_state["trade_mode"],
        trade_mode_after=system_state["trade_mode"],
        trading_state_before=system_state["trading_state"],
        trading_state_after=system_state["trading_state"],
        live_armed_before=system_state["live_armed"],
        live_armed_after=system_state["live_armed"],
        strategy_version_before=system_state["active_strategy_version_id"],
        strategy_version_after=system_state["active_strategy_version_id"],
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
