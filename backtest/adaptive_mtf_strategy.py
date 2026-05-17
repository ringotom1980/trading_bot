"""Adaptive multi-timeframe swing strategy replay.

This strategy is deliberately conservative: it only trades when the long-term
market regime and the mid-term momentum agree, then uses ATR stops to control
damage when that agreement fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk.risk_manager import RiskConfig, calculate_dynamic_position_size


@dataclass(frozen=True)
class AdaptiveMtfStrategyConfig:
    long_lookback_bars: int = 1920
    mid_lookback_bars: int = 384
    short_lookback_bars: int = 96
    long_threshold_pct: float = 0.025
    mid_threshold_pct: float = 0.008
    short_exhaustion_pct: float = 0.018
    confirm_bars: int = 12
    exit_confirm_bars: int = 4
    min_hold_bars: int = 96
    max_hold_bars: int = 1920
    atr_window: int = 96
    min_atr_pct: float = 0.0008
    max_atr_pct: float = 0.012
    hard_stop_atr_multiplier: float = 3.0
    trailing_atr_multiplier: float = 4.0
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    account_equity: float = 3391.35
    risk_per_trade_pct: float = 0.005
    leverage: float = 20.0
    min_qty: float = 0.001
    qty_step: float = 0.001


def _prefix_sum(values: list[float]) -> list[float]:
    prefix = [0.0]
    total = 0.0
    for value in values:
        total += value
        prefix.append(total)
    return prefix


def _window_average(prefix: list[float], *, end_idx: int, window: int) -> float:
    start_idx = end_idx - window + 1
    return (prefix[end_idx + 1] - prefix[start_idx]) / window


def _true_ranges(klines: list[dict[str, Any]], closes: list[float]) -> list[float]:
    values = [0.0]
    for idx in range(1, len(klines)):
        high = float(klines[idx]["high"])
        low = float(klines[idx]["low"])
        previous_close = closes[idx - 1]
        values.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return values


def _pct_change(closes: list[float], *, idx: int, lookback: int) -> float:
    base = closes[idx - lookback]
    return 0.0 if base == 0 else (closes[idx] - base) / base


def _side_from_momentum(momentum_pct: float, threshold_pct: float) -> str:
    if momentum_pct >= threshold_pct:
        return "LONG"
    if momentum_pct <= -threshold_pct:
        return "SHORT"
    return "FLAT"


def _entry_price(*, side: str, price: float, slippage_rate: float) -> float:
    if side == "LONG":
        return price * (1 + slippage_rate)
    if side == "SHORT":
        return price * (1 - slippage_rate)
    raise ValueError(f"unknown side: {side}")


def _exit_price(*, side: str, price: float, slippage_rate: float) -> float:
    if side == "LONG":
        return price * (1 - slippage_rate)
    if side == "SHORT":
        return price * (1 + slippage_rate)
    raise ValueError(f"unknown side: {side}")


def _gross_pnl(*, side: str, entry_price: float, exit_price: float, qty: float) -> float:
    if side == "LONG":
        return (exit_price - entry_price) * qty
    if side == "SHORT":
        return (entry_price - exit_price) * qty
    raise ValueError(f"unknown side: {side}")


def _confirmed(values: list[str], side: str, bars: int) -> bool:
    if bars <= 1:
        return bool(values and values[-1] == side)
    if len(values) < bars:
        return False
    return all(value == side for value in values[-bars:])


def _close_trade(
    *,
    position: dict[str, Any],
    exit_kline: dict[str, Any],
    exit_idx: int,
    raw_exit_price: float,
    close_reason: str,
    config: AdaptiveMtfStrategyConfig,
) -> dict[str, Any]:
    side = str(position["side"])
    qty = float(position["qty"])
    exit_price = _exit_price(
        side=side,
        price=raw_exit_price,
        slippage_rate=config.slippage_rate,
    )
    entry_price = float(position["entry_price"])
    gross = _gross_pnl(side=side, entry_price=entry_price, exit_price=exit_price, qty=qty)
    fees = (entry_price + exit_price) * qty * config.fee_rate
    return {
        "symbol": exit_kline["symbol"],
        "interval": exit_kline["interval"],
        "side": side,
        "entry_time": position["entry_time"],
        "exit_time": exit_kline["close_time"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": qty,
        "gross_pnl": gross,
        "fees": fees,
        "net_pnl": gross - fees,
        "bars_held": exit_idx - int(position["entry_idx"]),
        "close_reason": close_reason,
        "entry_feature_snapshot": dict(position.get("entry_feature_snapshot") or {}),
    }


def _desired_side(
    *,
    long_side: str,
    mid_side: str,
    short_momentum_pct: float,
    atr_pct: float,
    config: AdaptiveMtfStrategyConfig,
) -> str:
    if atr_pct < config.min_atr_pct or atr_pct > config.max_atr_pct:
        return "FLAT"
    if long_side not in {"LONG", "SHORT"}:
        return "FLAT"
    if mid_side != long_side:
        return "FLAT"
    if long_side == "LONG" and short_momentum_pct >= config.short_exhaustion_pct:
        return "FLAT"
    if long_side == "SHORT" and short_momentum_pct <= -config.short_exhaustion_pct:
        return "FLAT"
    return long_side


def run_adaptive_mtf_strategy_replay(
    *,
    klines: list[dict[str, Any]],
    config: AdaptiveMtfStrategyConfig,
) -> dict[str, Any]:
    min_bars = max(config.long_lookback_bars, config.atr_window + 1) + config.confirm_bars + 2
    if len(klines) < min_bars:
        raise ValueError("not enough klines for adaptive MTF strategy")

    closes = [float(kline["close"]) for kline in klines]
    tr_prefix = _prefix_sum(_true_ranges(klines, closes))
    start_idx = max(config.long_lookback_bars, config.atr_window + 1)
    desired_history: list[str] = []
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    equity = 0.0
    position: dict[str, Any] | None = None

    for idx in range(start_idx, len(klines)):
        latest = klines[idx]
        close = float(latest["close"])
        high = float(latest["high"])
        low = float(latest["low"])
        long_momentum_pct = _pct_change(closes, idx=idx, lookback=config.long_lookback_bars)
        mid_momentum_pct = _pct_change(closes, idx=idx, lookback=config.mid_lookback_bars)
        short_momentum_pct = _pct_change(closes, idx=idx, lookback=config.short_lookback_bars)
        long_side = _side_from_momentum(long_momentum_pct, config.long_threshold_pct)
        mid_side = _side_from_momentum(mid_momentum_pct, config.mid_threshold_pct)
        atr = _window_average(tr_prefix, end_idx=idx, window=config.atr_window)
        atr_pct = 0.0 if close == 0 else atr / close
        desired = _desired_side(
            long_side=long_side,
            mid_side=mid_side,
            short_momentum_pct=short_momentum_pct,
            atr_pct=atr_pct,
            config=config,
        )
        desired_history.append(desired)

        if position is None:
            if desired not in {"LONG", "SHORT"} or not _confirmed(desired_history, desired, config.confirm_bars):
                continue

            risk_config = RiskConfig(
                account_equity=config.account_equity + equity,
                risk_per_trade_pct=config.risk_per_trade_pct,
                leverage=config.leverage,
                atr_stop_multiplier=config.hard_stop_atr_multiplier,
                min_qty=config.min_qty,
                qty_step=config.qty_step,
            )
            sizing = calculate_dynamic_position_size(
                entry_price=close,
                atr_pct=atr_pct,
                config=risk_config,
            )
            if sizing.qty <= 0:
                continue

            entry = _entry_price(side=desired, price=close, slippage_rate=config.slippage_rate)
            stop_distance = entry * sizing.stop_pct
            position = {
                "side": desired,
                "qty": sizing.qty,
                "entry_idx": idx,
                "entry_time": latest["close_time"],
                "entry_price": entry,
                "hard_stop": entry - stop_distance if desired == "LONG" else entry + stop_distance,
                "trailing_stop": entry - stop_distance if desired == "LONG" else entry + stop_distance,
                "entry_feature_snapshot": {
                    "long_momentum_pct": long_momentum_pct,
                    "mid_momentum_pct": mid_momentum_pct,
                    "short_momentum_pct": short_momentum_pct,
                    "atr_pct": atr_pct,
                    "risk_usdt": sizing.risk_usdt,
                    "stop_pct": sizing.stop_pct,
                },
            }
            continue

        side = str(position["side"])
        bars_held = idx - int(position["entry_idx"])
        atr_distance = close * atr_pct * config.trailing_atr_multiplier
        exit_reason: str | None = None
        raw_exit_price: float | None = None

        if side == "LONG":
            position["trailing_stop"] = max(float(position["trailing_stop"]), close - atr_distance)
            if low <= float(position["hard_stop"]):
                exit_reason = "HARD_STOP"
                raw_exit_price = float(position["hard_stop"])
            elif bars_held >= config.min_hold_bars and low <= float(position["trailing_stop"]):
                exit_reason = "TRAILING_STOP"
                raw_exit_price = float(position["trailing_stop"])
            elif bars_held >= config.min_hold_bars and _confirmed(desired_history, "SHORT", config.exit_confirm_bars):
                exit_reason = "REVERSE_TO_SHORT"
                raw_exit_price = close
            elif bars_held >= config.min_hold_bars and _confirmed(desired_history, "FLAT", config.exit_confirm_bars):
                exit_reason = "SIGNAL_FLAT"
                raw_exit_price = close
        else:
            position["trailing_stop"] = min(float(position["trailing_stop"]), close + atr_distance)
            if high >= float(position["hard_stop"]):
                exit_reason = "HARD_STOP"
                raw_exit_price = float(position["hard_stop"])
            elif bars_held >= config.min_hold_bars and high >= float(position["trailing_stop"]):
                exit_reason = "TRAILING_STOP"
                raw_exit_price = float(position["trailing_stop"])
            elif bars_held >= config.min_hold_bars and _confirmed(desired_history, "LONG", config.exit_confirm_bars):
                exit_reason = "REVERSE_TO_LONG"
                raw_exit_price = close
            elif bars_held >= config.min_hold_bars and _confirmed(desired_history, "FLAT", config.exit_confirm_bars):
                exit_reason = "SIGNAL_FLAT"
                raw_exit_price = close

        if exit_reason is None and bars_held >= config.max_hold_bars:
            exit_reason = "MAX_HOLD"
            raw_exit_price = close

        if exit_reason is None:
            continue

        assert raw_exit_price is not None
        trade = _close_trade(
            position=position,
            exit_kline=latest,
            exit_idx=idx,
            raw_exit_price=raw_exit_price,
            close_reason=exit_reason,
            config=config,
        )
        trades.append(trade)
        equity += float(trade["net_pnl"])
        equity_curve.append(equity)
        position = None

    if position is not None:
        trade = _close_trade(
            position=position,
            exit_kline=klines[-1],
            exit_idx=len(klines) - 1,
            raw_exit_price=float(klines[-1]["close"]),
            close_reason="END_OF_RANGE",
            config=config,
        )
        trades.append(trade)
        equity += float(trade["net_pnl"])
        equity_curve.append(equity)

    return {
        "trades": trades,
        "equity_curve": equity_curve,
    }
