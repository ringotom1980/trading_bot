"""
Path: backtest/replay_engine.py
說明：Backtest v3 重放引擎，依 historical_klines 逐根計算 feature / signal / decision，
並模擬持倉開平倉，支援 cooldown_bars / min_hold_bars / max_bars_hold /
hard_stop_loss_pct / take_profit_pct。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from strategy.decision import calculate_decision
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores

DIAGNOSTIC_FEATURE_KEYS = [
    "rsi_14",
    "macd_hist",
    "kd_diff",
    "close_vs_sma20_pct",
    "close_vs_sma60_pct",
    "slope_5",
    "slope_10",
    "atr_14_pct",
    "volatility_10",
    "volume_ratio_20",
    "volume_slope_5",
    "regime",
    "regime_score",
]


def _calc_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    qty: float,
) -> float:
    if side == "LONG":
        return (exit_price - entry_price) * qty

    if side == "SHORT":
        return (entry_price - exit_price) * qty

    raise ValueError(f"不支援的 side：{side}")


def _to_bar_close_time_value(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)

    return int(value)


def _calc_return_pct(*, side: str, entry_price: float, current_price: float) -> float:
    if entry_price == 0:
        return 0.0

    if side == "LONG":
        return (current_price - entry_price) / entry_price

    if side == "SHORT":
        return (entry_price - current_price) / entry_price

    raise ValueError(f"不支援的 side：{side}")


def _apply_entry_slippage(*, side: str, price: float, slippage_rate: float) -> float:
    if side == "LONG":
        return price * (1 + slippage_rate)
    if side == "SHORT":
        return price * (1 - slippage_rate)
    raise ValueError(f"不支援的 side：{side}")


def _apply_exit_slippage(*, side: str, price: float, slippage_rate: float) -> float:
    if side == "LONG":
        return price * (1 - slippage_rate)
    if side == "SHORT":
        return price * (1 + slippage_rate)
    raise ValueError(f"不支援的 side：{side}")


def _resolve_risk_exit_price(
    *,
    side: str,
    entry_price: float,
    high_price: float,
    low_price: float,
    hard_stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[str | None, float | None]:
    stop_loss_hit = False
    take_profit_hit = False
    stop_loss_price: float | None = None
    take_profit_price: float | None = None

    if side == "LONG":
        if hard_stop_loss_pct > 0:
            stop_loss_price = entry_price * (1 - hard_stop_loss_pct)
            stop_loss_hit = low_price <= stop_loss_price
        if take_profit_pct > 0:
            take_profit_price = entry_price * (1 + take_profit_pct)
            take_profit_hit = high_price >= take_profit_price

    elif side == "SHORT":
        if hard_stop_loss_pct > 0:
            stop_loss_price = entry_price * (1 + hard_stop_loss_pct)
            stop_loss_hit = high_price >= stop_loss_price
        if take_profit_pct > 0:
            take_profit_price = entry_price * (1 - take_profit_pct)
            take_profit_hit = low_price <= take_profit_price

    else:
        raise ValueError(f"不支援的 side：{side}")

    if stop_loss_hit:
        return "HARD_STOP_LOSS", stop_loss_price

    if take_profit_hit:
        return "TAKE_PROFIT", take_profit_price

    return None, None


def _build_entry_feature_snapshot(feature_pack: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}

    for key in DIAGNOSTIC_FEATURE_KEYS:
        if key in feature_pack:
            snapshot[key] = feature_pack[key]

    return snapshot


def _build_open_position(
    *,
    strategy_version_id: int,
    symbol: str,
    interval: str,
    side: str,
    close_time: Any,
    idx: int,
    close_price: float,
    qty: float,
    fee_rate: float,
    slippage_rate: float,
    effective_decision: str,
    effective_reason: str,
    signal_scores: dict[str, Any],
    feature_pack: dict[str, Any],
) -> dict[str, Any]:
    entry_price = _apply_entry_slippage(
        side=side,
        price=close_price,
        slippage_rate=slippage_rate,
    )
    entry_fee = entry_price * qty * fee_rate

    return {
        "strategy_version_id": strategy_version_id,
        "symbol": symbol,
        "interval": interval,
        "side": side,
        "entry_price": entry_price,
        "entry_qty": qty,
        "entry_time": close_time,
        "entry_bar_index": idx,
        "entry_fee": entry_fee,
        "entry_decision": effective_decision,
        "entry_reason_code": effective_reason,
        "entry_long_score": float(signal_scores["long_score"]),
        "entry_short_score": float(signal_scores["short_score"]),
        "entry_feature_snapshot": _build_entry_feature_snapshot(feature_pack),
    }


def _close_position(
    *,
    current_position: dict[str, Any],
    close_time: Any,
    close_price: float,
    raw_exit_price: float,
    qty: float,
    fee_rate: float,
    slippage_rate: float,
    idx: int,
    effective_reason: str,
) -> tuple[dict[str, Any], float]:
    exit_price = _apply_exit_slippage(
        side=str(current_position["side"]),
        price=raw_exit_price,
        slippage_rate=slippage_rate,
    )
    gross_pnl = _calc_pnl(
        side=current_position["side"],
        entry_price=float(current_position["entry_price"]),
        exit_price=exit_price,
        qty=qty,
    )
    exit_fee = exit_price * qty * fee_rate
    fees = float(current_position["entry_fee"]) + exit_fee
    net_pnl = gross_pnl - fees
    bars_held = idx - int(current_position["entry_bar_index"])

    trade = {
        "strategy_version_id": current_position["strategy_version_id"],
        "symbol": current_position["symbol"],
        "interval": current_position["interval"],
        "side": current_position["side"],
        "entry_time": current_position["entry_time"],
        "exit_time": close_time,
        "entry_price": float(current_position["entry_price"]),
        "exit_price": exit_price,
        "exit_trigger_price": raw_exit_price,
        "exit_bar_close_price": close_price,
        "qty": qty,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "bars_held": bars_held,
        "entry_decision": current_position.get("entry_decision"),
        "entry_reason_code": current_position.get("entry_reason_code"),
        "entry_long_score": current_position.get("entry_long_score"),
        "entry_short_score": current_position.get("entry_short_score"),
        "entry_feature_snapshot": dict(current_position.get("entry_feature_snapshot") or {}),
        "exit_reason": effective_reason,
    }
    return trade, net_pnl


def run_backtest_replay(
    *,
    klines: list[dict[str, Any]],
    strategy_version_id: int,
    symbol: str,
    interval: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if len(klines) < 61:
        raise ValueError("回測資料不足，至少需要 61 根 K 線")

    qty = float(params.get("qty", 0.01))
    fee_rate = float(params.get("fee_rate", 0.0004))
    slippage_rate = float(params.get("slippage_rate", 0.0005))
    warmup_bars = int(params.get("warmup_bars", 60))
    cooldown_bars = int(params.get("cooldown_bars", 0))
    min_hold_bars = int(params.get("min_hold_bars", 0))
    max_bars_hold = int(params.get("max_bars_hold", 0))
    hard_stop_loss_pct = float(params.get("hard_stop_loss_pct", 0.0))
    take_profit_pct = float(params.get("take_profit_pct", 0.0))

    if warmup_bars < 60:
        warmup_bars = 60

    current_position: dict[str, Any] | None = None
    last_exit_bar_index: int | None = None

    equity = 0.0
    equity_curve: list[float] = []
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for idx in range(warmup_bars - 1, len(klines)):
        window = klines[: idx + 1]
        latest = window[-1]

        feature_pack = calculate_feature_pack(
            symbol=symbol,
            interval=interval,
            klines=window[-60:],
        )

        signal_scores = calculate_signal_scores(feature_pack, params)

        decision_result = calculate_decision(
            long_score=signal_scores["long_score"],
            short_score=signal_scores["short_score"],
            current_position_side=current_position["side"] if current_position else None,
            params=params,
        )

        close_price = float(latest["close"])
        high_price = float(latest["high"])
        low_price = float(latest["low"])
        close_time = latest["close_time"]

        effective_decision = decision_result["decision"]
        effective_reason = decision_result["reason_code"]
        risk_exit_price: float | None = None

        if current_position is None:
            if effective_decision in {"ENTER_LONG", "ENTER_SHORT"} and last_exit_bar_index is not None:
                bars_since_exit = idx - last_exit_bar_index
                if bars_since_exit < cooldown_bars:
                    effective_decision = "WAIT"
                    effective_reason = "COOLDOWN_BLOCKED"

        else:
            bars_held = idx - int(current_position["entry_bar_index"])
            position_side = str(current_position["side"])
            entry_price = float(current_position["entry_price"])

            risk_exit_reason, risk_exit_price = _resolve_risk_exit_price(
                side=position_side,
                entry_price=entry_price,
                high_price=high_price,
                low_price=low_price,
                hard_stop_loss_pct=hard_stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )

            if risk_exit_reason is not None:
                effective_decision = "EXIT"
                effective_reason = risk_exit_reason

            elif max_bars_hold > 0 and bars_held >= max_bars_hold:
                effective_decision = "EXIT"
                effective_reason = "MAX_BARS_HOLD_EXIT"

            elif effective_decision in {"EXIT", "REVERSE_TO_LONG", "REVERSE_TO_SHORT"} and bars_held < min_hold_bars:
                effective_decision = "HOLD"
                effective_reason = "MIN_HOLD_BLOCKED"

        decisions.append(
            {
                "bar_close_time": _to_bar_close_time_value(latest["close_time"]),
                "decision": effective_decision,
                "reason_code": effective_reason,
                "long_score": float(signal_scores["long_score"]),
                "short_score": float(signal_scores["short_score"]),
            }
        )

        if current_position is None:
            if effective_decision == "ENTER_LONG":
                current_position = _build_open_position(
                    strategy_version_id=strategy_version_id,
                    symbol=symbol,
                    interval=interval,
                    side="LONG",
                    close_time=close_time,
                    idx=idx,
                    close_price=close_price,
                    qty=qty,
                    fee_rate=fee_rate,
                    slippage_rate=slippage_rate,
                    effective_decision=effective_decision,
                    effective_reason=effective_reason,
                    signal_scores=signal_scores,
                    feature_pack=feature_pack,
                )

            elif effective_decision == "ENTER_SHORT":
                current_position = _build_open_position(
                    strategy_version_id=strategy_version_id,
                    symbol=symbol,
                    interval=interval,
                    side="SHORT",
                    close_time=close_time,
                    idx=idx,
                    close_price=close_price,
                    qty=qty,
                    fee_rate=fee_rate,
                    slippage_rate=slippage_rate,
                    effective_decision=effective_decision,
                    effective_reason=effective_reason,
                    signal_scores=signal_scores,
                    feature_pack=feature_pack,
                )

        else:
            if effective_decision in {"EXIT", "REVERSE_TO_LONG", "REVERSE_TO_SHORT"}:
                raw_exit_price = risk_exit_price if risk_exit_price is not None else close_price
                trade, net_pnl = _close_position(
                    current_position=current_position,
                    close_time=close_time,
                    close_price=close_price,
                    raw_exit_price=raw_exit_price,
                    qty=qty,
                    fee_rate=fee_rate,
                    slippage_rate=slippage_rate,
                    idx=idx,
                    effective_reason=effective_reason,
                )
                trades.append(trade)

                equity += net_pnl
                equity_curve.append(equity)
                current_position = None
                last_exit_bar_index = idx

                if effective_decision == "REVERSE_TO_LONG":
                    current_position = _build_open_position(
                        strategy_version_id=strategy_version_id,
                        symbol=symbol,
                        interval=interval,
                        side="LONG",
                        close_time=close_time,
                        idx=idx,
                        close_price=close_price,
                        qty=qty,
                        fee_rate=fee_rate,
                        slippage_rate=slippage_rate,
                        effective_decision=effective_decision,
                        effective_reason=effective_reason,
                        signal_scores=signal_scores,
                        feature_pack=feature_pack,
                    )

                elif effective_decision == "REVERSE_TO_SHORT":
                    current_position = _build_open_position(
                        strategy_version_id=strategy_version_id,
                        symbol=symbol,
                        interval=interval,
                        side="SHORT",
                        close_time=close_time,
                        idx=idx,
                        close_price=close_price,
                        qty=qty,
                        fee_rate=fee_rate,
                        slippage_rate=slippage_rate,
                        effective_decision=effective_decision,
                        effective_reason=effective_reason,
                        signal_scores=signal_scores,
                        feature_pack=feature_pack,
                    )

        if current_position is not None:
            mark_price = close_price
            mark_return_pct = _calc_return_pct(
                side=str(current_position["side"]),
                entry_price=float(current_position["entry_price"]),
                current_price=mark_price,
            )
            current_position["mark_return_pct"] = mark_return_pct

    if current_position is not None:
        last_bar = klines[-1]
        final_close_price = float(last_bar["close"])
        final_close_time = last_bar["close_time"]

        trade, net_pnl = _close_position(
            current_position=current_position,
            close_time=final_close_time,
            close_price=final_close_price,
            raw_exit_price=final_close_price,
            qty=qty,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            idx=len(klines) - 1,
            effective_reason="FORCED_END_OF_BACKTEST",
        )
        trades.append(trade)

        equity += net_pnl
        equity_curve.append(equity)

    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version_id": strategy_version_id,
        "trade_count": len(trades),
        "trades": trades,
        "decisions": decisions,
        "equity_curve": equity_curve,
    }