"""Regime-first low-frequency swing strategy replay."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from risk.risk_manager import RiskConfig, calculate_dynamic_position_size


@dataclass(frozen=True)
class RegimeStrategyConfig:
    fast_window: int = 240
    slow_window: int = 960
    confirm_bars: int = 16
    exit_confirm_bars: int = 8
    min_hold_bars: int = 96
    max_hold_bars: int = 2880
    entry_gap_pct: float = 0.010
    exit_gap_pct: float = 0.002
    slope_window: int = 240
    atr_window: int = 96
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    account_equity: float = 3391.35
    risk_per_trade_pct: float = 0.005
    leverage: float = 20.0
    hard_stop_atr_multiplier: float = 3.0
    trailing_atr_multiplier: float = 4.0
    min_qty: float = 0.001
    qty_step: float = 0.001


def _sma(values: list[float], window: int) -> float:
    return mean(values[-window:])


def _atr_pct(klines: list[dict[str, Any]], window: int) -> float:
    if len(klines) < window + 1:
        return 0.0

    true_ranges: list[float] = []
    for idx in range(len(klines) - window, len(klines)):
        high = float(klines[idx]["high"])
        low = float(klines[idx]["low"])
        prev_close = float(klines[idx - 1]["close"])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    latest_close = float(klines[-1]["close"])
    if latest_close == 0:
        return 0.0
    return mean(true_ranges) / latest_close


def _regime_signal(
    *,
    closes: list[float],
    config: RegimeStrategyConfig,
) -> str:
    fast = _sma(closes, config.fast_window)
    slow = _sma(closes, config.slow_window)
    gap = 0.0 if slow == 0 else (fast - slow) / slow
    slope = closes[-1] - closes[-config.slope_window]

    if gap >= config.entry_gap_pct and slope > 0:
        return "LONG"
    if gap <= -config.entry_gap_pct and slope < 0:
        return "SHORT"
    if abs(gap) <= config.exit_gap_pct:
        return "FLAT"
    return "NEUTRAL"


def _confirmed_signal(signals: list[str], signal: str, bars: int) -> bool:
    if bars <= 1:
        return bool(signals and signals[-1] == signal)
    if len(signals) < bars:
        return False
    return all(item == signal for item in signals[-bars:])


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


def _calc_gross_pnl(*, side: str, entry_price: float, exit_price: float, qty: float) -> float:
    if side == "LONG":
        return (exit_price - entry_price) * qty
    if side == "SHORT":
        return (entry_price - exit_price) * qty
    raise ValueError(f"unknown side: {side}")


def _close_trade(
    *,
    position: dict[str, Any],
    exit_kline: dict[str, Any],
    exit_idx: int,
    raw_exit_price: float,
    close_reason: str,
    config: RegimeStrategyConfig,
) -> dict[str, Any]:
    side = str(position["side"])
    qty = float(position["qty"])
    exit_price = _exit_price(
        side=side,
        price=raw_exit_price,
        slippage_rate=config.slippage_rate,
    )
    entry_price = float(position["entry_price"])
    gross_pnl = _calc_gross_pnl(
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        qty=qty,
    )
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
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": gross_pnl - fees,
        "bars_held": exit_idx - int(position["entry_idx"]),
        "close_reason": close_reason,
        "entry_feature_snapshot": dict(position.get("entry_feature_snapshot") or {}),
    }


def run_regime_strategy_replay(
    *,
    klines: list[dict[str, Any]],
    config: RegimeStrategyConfig,
) -> dict[str, Any]:
    if len(klines) < config.slow_window + 2:
        raise ValueError("not enough klines for regime strategy")

    closes = [float(kline["close"]) for kline in klines]
    start_idx = max(config.slow_window, config.atr_window + 1, config.slope_window)
    signals: list[str] = []
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    equity = 0.0
    position: dict[str, Any] | None = None

    for idx in range(start_idx, len(klines)):
        window_closes = closes[: idx + 1]
        latest = klines[idx]
        close = float(latest["close"])
        high = float(latest["high"])
        low = float(latest["low"])
        atr_pct = _atr_pct(klines[: idx + 1], config.atr_window)
        signal = _regime_signal(closes=window_closes, config=config)
        signals.append(signal)

        if position is None:
            desired_side: str | None = None
            if _confirmed_signal(signals, "LONG", config.confirm_bars):
                desired_side = "LONG"
            elif _confirmed_signal(signals, "SHORT", config.confirm_bars):
                desired_side = "SHORT"

            if desired_side is None:
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

            entry = _entry_price(
                side=desired_side,
                price=close,
                slippage_rate=config.slippage_rate,
            )
            stop_distance = entry * sizing.stop_pct
            if desired_side == "LONG":
                hard_stop = entry - stop_distance
                trailing_stop = hard_stop
            else:
                hard_stop = entry + stop_distance
                trailing_stop = hard_stop

            position = {
                "side": desired_side,
                "qty": sizing.qty,
                "entry_idx": idx,
                "entry_time": latest["close_time"],
                "entry_price": entry,
                "hard_stop": hard_stop,
                "trailing_stop": trailing_stop,
                "entry_feature_snapshot": {
                    "regime_signal": signal,
                    "atr_pct": atr_pct,
                    "risk_usdt": sizing.risk_usdt,
                    "stop_pct": sizing.stop_pct,
                },
            }
            continue

        side = str(position["side"])
        bars_held = idx - int(position["entry_idx"])
        exit_reason: str | None = None
        raw_exit_price: float | None = None
        atr_distance = close * atr_pct * config.trailing_atr_multiplier

        if side == "LONG":
            position["trailing_stop"] = max(float(position["trailing_stop"]), close - atr_distance)
            if low <= float(position["hard_stop"]):
                exit_reason = "HARD_STOP"
                raw_exit_price = float(position["hard_stop"])
            elif low <= float(position["trailing_stop"]) and bars_held >= config.min_hold_bars:
                exit_reason = "TRAILING_STOP"
                raw_exit_price = float(position["trailing_stop"])
            elif _confirmed_signal(signals, "SHORT", config.exit_confirm_bars) and bars_held >= config.min_hold_bars:
                exit_reason = "REVERSE_TO_SHORT"
                raw_exit_price = close
            elif _confirmed_signal(signals, "FLAT", config.exit_confirm_bars) and bars_held >= config.min_hold_bars:
                exit_reason = "REGIME_FLAT"
                raw_exit_price = close
        else:
            position["trailing_stop"] = min(float(position["trailing_stop"]), close + atr_distance)
            if high >= float(position["hard_stop"]):
                exit_reason = "HARD_STOP"
                raw_exit_price = float(position["hard_stop"])
            elif high >= float(position["trailing_stop"]) and bars_held >= config.min_hold_bars:
                exit_reason = "TRAILING_STOP"
                raw_exit_price = float(position["trailing_stop"])
            elif _confirmed_signal(signals, "LONG", config.exit_confirm_bars) and bars_held >= config.min_hold_bars:
                exit_reason = "REVERSE_TO_LONG"
                raw_exit_price = close
            elif _confirmed_signal(signals, "FLAT", config.exit_confirm_bars) and bars_held >= config.min_hold_bars:
                exit_reason = "REGIME_FLAT"
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

