"""Simple baselines used to judge whether a strategy has a real edge."""

from __future__ import annotations

from statistics import mean
from typing import Any


def _sma(values: list[float], window: int) -> float:
    return mean(values[-window:])


def _calc_net_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    qty: float,
    fee_rate: float,
    slippage_rate: float,
) -> dict[str, float]:
    if side == "LONG":
        slipped_entry = entry_price * (1 + slippage_rate)
        slipped_exit = exit_price * (1 - slippage_rate)
        gross = (slipped_exit - slipped_entry) * qty
    elif side == "SHORT":
        slipped_entry = entry_price * (1 - slippage_rate)
        slipped_exit = exit_price * (1 + slippage_rate)
        gross = (slipped_entry - slipped_exit) * qty
    else:
        raise ValueError(f"unknown side: {side}")

    fees = (slipped_entry + slipped_exit) * qty * fee_rate
    return {
        "entry_price": slipped_entry,
        "exit_price": slipped_exit,
        "gross_pnl": gross,
        "fees": fees,
        "net_pnl": gross - fees,
    }


def _trade(
    *,
    side: str,
    entry: dict[str, Any],
    exit_: dict[str, Any],
    qty: float,
    fee_rate: float,
    slippage_rate: float,
    close_reason: str,
) -> dict[str, Any]:
    pnl = _calc_net_pnl(
        side=side,
        entry_price=float(entry["close"]),
        exit_price=float(exit_["close"]),
        qty=qty,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
    return {
        "symbol": entry["symbol"],
        "interval": entry["interval"],
        "side": side,
        "entry_time": entry["close_time"],
        "exit_time": exit_["close_time"],
        "entry_price": pnl["entry_price"],
        "exit_price": pnl["exit_price"],
        "qty": qty,
        "gross_pnl": pnl["gross_pnl"],
        "fees": pnl["fees"],
        "net_pnl": pnl["net_pnl"],
        "bars_held": 0,
        "close_reason": close_reason,
        "entry_feature_snapshot": {},
    }


def _equity_curve_from_trades(trades: list[dict[str, Any]]) -> list[float]:
    equity = 0.0
    curve: list[float] = []
    for trade in trades:
        equity += float(trade["net_pnl"])
        curve.append(equity)
    return curve


def buy_and_hold_baseline(
    *,
    klines: list[dict[str, Any]],
    side: str,
    qty: float = 0.01,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    if len(klines) < 2:
        return {"trades": [], "equity_curve": []}
    trade = _trade(
        side=side,
        entry=klines[0],
        exit_=klines[-1],
        qty=qty,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        close_reason="END_OF_RANGE",
    )
    trade["bars_held"] = len(klines) - 1
    return {"trades": [trade], "equity_curve": _equity_curve_from_trades([trade])}


def sma_regime_flip_baseline(
    *,
    klines: list[dict[str, Any]],
    fast_window: int = 60,
    slow_window: int = 240,
    qty: float = 0.01,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    closes = [float(k["close"]) for k in klines]
    trades: list[dict[str, Any]] = []
    position_side: str | None = None
    entry_kline: dict[str, Any] | None = None
    entry_idx = 0

    for idx in range(slow_window, len(klines)):
        fast = _sma(closes[: idx + 1], fast_window)
        slow = _sma(closes[: idx + 1], slow_window)
        desired_side = "LONG" if fast > slow else "SHORT"

        if position_side is None:
            position_side = desired_side
            entry_kline = klines[idx]
            entry_idx = idx
            continue

        if desired_side == position_side:
            continue

        assert entry_kline is not None
        trade = _trade(
            side=position_side,
            entry=entry_kline,
            exit_=klines[idx],
            qty=qty,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            close_reason="SMA_REGIME_FLIP",
        )
        trade["bars_held"] = idx - entry_idx
        trades.append(trade)

        position_side = desired_side
        entry_kline = klines[idx]
        entry_idx = idx

    if position_side is not None and entry_kline is not None:
        trade = _trade(
            side=position_side,
            entry=entry_kline,
            exit_=klines[-1],
            qty=qty,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            close_reason="END_OF_RANGE",
        )
        trade["bars_held"] = len(klines) - 1 - entry_idx
        trades.append(trade)

    return {"trades": trades, "equity_curve": _equity_curve_from_trades(trades)}


def channel_breakout_baseline(
    *,
    klines: list[dict[str, Any]],
    lookback: int = 96,
    max_hold_bars: int = 384,
    qty: float = 0.01,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    position_side: str | None = None
    entry_kline: dict[str, Any] | None = None
    entry_idx = 0

    for idx in range(lookback, len(klines)):
        previous = klines[idx - lookback: idx]
        channel_high = max(float(k["high"]) for k in previous)
        channel_low = min(float(k["low"]) for k in previous)
        close = float(klines[idx]["close"])

        breakout_side: str | None = None
        if close > channel_high:
            breakout_side = "LONG"
        elif close < channel_low:
            breakout_side = "SHORT"

        if position_side is None:
            if breakout_side is not None:
                position_side = breakout_side
                entry_kline = klines[idx]
                entry_idx = idx
            continue

        should_exit = idx - entry_idx >= max_hold_bars
        should_reverse = breakout_side is not None and breakout_side != position_side
        if not should_exit and not should_reverse:
            continue

        assert entry_kline is not None
        trade = _trade(
            side=position_side,
            entry=entry_kline,
            exit_=klines[idx],
            qty=qty,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            close_reason="CHANNEL_REVERSE" if should_reverse else "MAX_HOLD",
        )
        trade["bars_held"] = idx - entry_idx
        trades.append(trade)

        position_side = breakout_side if should_reverse else None
        entry_kline = klines[idx] if should_reverse else None
        entry_idx = idx

    if position_side is not None and entry_kline is not None:
        trade = _trade(
            side=position_side,
            entry=entry_kline,
            exit_=klines[-1],
            qty=qty,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            close_reason="END_OF_RANGE",
        )
        trade["bars_held"] = len(klines) - 1 - entry_idx
        trades.append(trade)

    return {"trades": trades, "equity_curve": _equity_curve_from_trades(trades)}

