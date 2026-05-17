"""Long-horizon momentum strategy replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MomentumStrategyConfig:
    lookback_bars: int = 1920
    threshold_pct: float = 0.03
    confirm_bars: int = 96
    min_hold_bars: int = 384
    qty: float = 0.01
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005


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


def _confirmed_signal(signals: list[str], signal: str, bars: int) -> bool:
    if bars <= 1:
        return bool(signals and signals[-1] == signal)
    if len(signals) < bars:
        return False
    return all(item == signal for item in signals[-bars:])


def _close_trade(
    *,
    position: dict[str, Any],
    exit_kline: dict[str, Any],
    exit_idx: int,
    config: MomentumStrategyConfig,
    close_reason: str,
) -> dict[str, Any]:
    side = str(position["side"])
    qty = float(position["qty"])
    exit_price = _exit_price(
        side=side,
        price=float(exit_kline["close"]),
        slippage_rate=config.slippage_rate,
    )
    entry_price = float(position["entry_price"])
    gross = _gross_pnl(
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
        "gross_pnl": gross,
        "fees": fees,
        "net_pnl": gross - fees,
        "bars_held": exit_idx - int(position["entry_idx"]),
        "close_reason": close_reason,
        "entry_feature_snapshot": dict(position.get("entry_feature_snapshot") or {}),
    }


def run_momentum_strategy_replay(
    *,
    klines: list[dict[str, Any]],
    config: MomentumStrategyConfig,
) -> dict[str, Any]:
    if len(klines) < config.lookback_bars + config.confirm_bars + 2:
        raise ValueError("not enough klines for momentum strategy")

    closes = [float(kline["close"]) for kline in klines]
    signals: list[str] = []
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    equity = 0.0
    position: dict[str, Any] | None = None

    for idx in range(config.lookback_bars, len(klines)):
        base_close = closes[idx - config.lookback_bars]
        current_close = closes[idx]
        momentum_pct = 0.0 if base_close == 0 else (current_close - base_close) / base_close

        if momentum_pct >= config.threshold_pct:
            signal = "LONG"
        elif momentum_pct <= -config.threshold_pct:
            signal = "SHORT"
        else:
            signal = "FLAT"

        signals.append(signal)
        confirmed = _confirmed_signal(signals, signal, config.confirm_bars)

        if position is None:
            if confirmed and signal in {"LONG", "SHORT"}:
                position = {
                    "side": signal,
                    "qty": config.qty,
                    "entry_idx": idx,
                    "entry_time": klines[idx]["close_time"],
                    "entry_price": _entry_price(
                        side=signal,
                        price=current_close,
                        slippage_rate=config.slippage_rate,
                    ),
                    "entry_feature_snapshot": {
                        "momentum_pct": momentum_pct,
                        "lookback_bars": config.lookback_bars,
                        "threshold_pct": config.threshold_pct,
                    },
                }
            continue

        bars_held = idx - int(position["entry_idx"])
        if bars_held < config.min_hold_bars or not confirmed or signal == position["side"]:
            continue

        trade = _close_trade(
            position=position,
            exit_kline=klines[idx],
            exit_idx=idx,
            config=config,
            close_reason="MOMENTUM_FLIP",
        )
        trades.append(trade)
        equity += float(trade["net_pnl"])
        equity_curve.append(equity)
        position = None

        if signal in {"LONG", "SHORT"}:
            position = {
                "side": signal,
                "qty": config.qty,
                "entry_idx": idx,
                "entry_time": klines[idx]["close_time"],
                "entry_price": _entry_price(
                    side=signal,
                    price=current_close,
                    slippage_rate=config.slippage_rate,
                ),
                "entry_feature_snapshot": {
                    "momentum_pct": momentum_pct,
                    "lookback_bars": config.lookback_bars,
                    "threshold_pct": config.threshold_pct,
                },
            }

    if position is not None:
        trade = _close_trade(
            position=position,
            exit_kline=klines[-1],
            exit_idx=len(klines) - 1,
            config=config,
            close_reason="END_OF_RANGE",
        )
        trades.append(trade)
        equity += float(trade["net_pnl"])
        equity_curve.append(equity)

    return {
        "trades": trades,
        "equity_curve": equity_curve,
    }

