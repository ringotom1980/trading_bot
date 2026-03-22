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


def _calc_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    qty: float,
) -> float:
    """
    功能：計算單筆交易 gross pnl。
    """
    if side == "LONG":
        return (exit_price - entry_price) * qty

    if side == "SHORT":
        return (entry_price - exit_price) * qty

    raise ValueError(f"不支援的 side：{side}")


def _to_bar_close_time_value(value: Any) -> int:
    """
    功能：將 close_time 統一轉為毫秒時間戳整數。
    """
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)

    return int(value)


def _calc_return_pct(*, side: str, entry_price: float, current_price: float) -> float:
    """
    功能：計算目前持倉報酬率。
    """
    if entry_price == 0:
        return 0.0

    if side == "LONG":
        return (current_price - entry_price) / entry_price

    if side == "SHORT":
        return (entry_price - current_price) / entry_price

    raise ValueError(f"不支援的 side：{side}")


def run_backtest_replay(
    *,
    klines: list[dict[str, Any]],
    strategy_version_id: int,
    symbol: str,
    interval: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    功能：執行 Backtest v3。
    說明：
        - 使用與 runtime 同源的 feature / signal / decision
        - 以 historical_klines 逐根重放
        - 支援 cooldown_bars / min_hold_bars / max_bars_hold
        - 支援 hard_stop_loss_pct / take_profit_pct
    """
    if len(klines) < 61:
        raise ValueError("回測資料不足，至少需要 61 根 K 線")

    qty = float(params.get("qty", 0.01))
    fee_rate = float(params.get("fee_rate", 0.0004))
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
        close_time = latest["close_time"]

        effective_decision = decision_result["decision"]
        effective_reason = decision_result["reason_code"]

        if current_position is None:
            if effective_decision in {"ENTER_LONG", "ENTER_SHORT"} and last_exit_bar_index is not None:
                bars_since_exit = idx - last_exit_bar_index
                if bars_since_exit < cooldown_bars:
                    effective_decision = "WAIT"
                    effective_reason = "COOLDOWN_BLOCKED"

        else:
            bars_held = idx - int(current_position["entry_bar_index"])
            current_return_pct = _calc_return_pct(
                side=str(current_position["side"]),
                entry_price=float(current_position["entry_price"]),
                current_price=close_price,
            )

            if hard_stop_loss_pct > 0 and current_return_pct <= -hard_stop_loss_pct:
                effective_decision = "EXIT"
                effective_reason = "HARD_STOP_LOSS"

            elif take_profit_pct > 0 and current_return_pct >= take_profit_pct:
                effective_decision = "EXIT"
                effective_reason = "TAKE_PROFIT"

            elif max_bars_hold > 0 and bars_held >= max_bars_hold:
                effective_decision = "EXIT"
                effective_reason = "MAX_BARS_HOLD_EXIT"

            elif effective_decision == "EXIT" and bars_held < min_hold_bars:
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
                entry_fee = close_price * qty * fee_rate
                current_position = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": "LONG",
                    "entry_price": close_price,
                    "entry_qty": qty,
                    "entry_time": close_time,
                    "entry_bar_index": idx,
                    "entry_fee": entry_fee,
                    "entry_decision": effective_decision,
                }

            elif effective_decision == "ENTER_SHORT":
                entry_fee = close_price * qty * fee_rate
                current_position = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": "SHORT",
                    "entry_price": close_price,
                    "entry_qty": qty,
                    "entry_time": close_time,
                    "entry_bar_index": idx,
                    "entry_fee": entry_fee,
                    "entry_decision": effective_decision,
                }

        else:
            if effective_decision == "EXIT":
                gross_pnl = _calc_pnl(
                    side=current_position["side"],
                    entry_price=float(current_position["entry_price"]),
                    exit_price=close_price,
                    qty=qty,
                )
                exit_fee = close_price * qty * fee_rate
                fees = float(current_position["entry_fee"]) + exit_fee
                net_pnl = gross_pnl - fees
                bars_held = idx - int(current_position["entry_bar_index"])

                trade = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": current_position["side"],
                    "entry_time": current_position["entry_time"],
                    "exit_time": close_time,
                    "entry_price": float(current_position["entry_price"]),
                    "exit_price": close_price,
                    "qty": qty,
                    "gross_pnl": gross_pnl,
                    "fees": fees,
                    "net_pnl": net_pnl,
                    "bars_held": bars_held,
                    "exit_reason": effective_reason,
                }
                trades.append(trade)

                equity += net_pnl
                equity_curve.append(equity)
                current_position = None
                last_exit_bar_index = idx

    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version_id": strategy_version_id,
        "trade_count": len(trades),
        "trades": trades,
        "decisions": decisions,
        "equity_curve": equity_curve,
    }