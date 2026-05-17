"""Long-horizon momentum strategy replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk.risk_manager import RiskConfig, calculate_dynamic_position_size


@dataclass(frozen=True)
class MomentumStrategyConfig:
    lookback_bars: int = 1920
    threshold_pct: float = 0.03
    confirm_bars: int = 96
    min_hold_bars: int = 384
    qty: float = 0.01
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    sizing_mode: str = "FIXED_QTY"
    initial_equity: float = 100.0
    risk_per_trade_pct: float = 0.005
    margin_per_trade_pct: float = 0.25
    leverage: float = 20.0
    atr_window: int = 96
    hard_stop_atr_multiplier: float = 2.5
    min_qty: float = 0.001
    qty_step: float = 0.001


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


def _atr_pct(
    *,
    tr_prefix: list[float],
    close: float,
    idx: int,
    window: int,
) -> float:
    if idx < window or close == 0:
        return 0.0
    atr = _window_average(tr_prefix, end_idx=idx, window=window)
    return atr / close


def _calculate_entry_qty(
    *,
    close: float,
    atr_pct: float,
    equity: float,
    config: MomentumStrategyConfig,
) -> tuple[float, dict[str, Any]]:
    if config.sizing_mode == "FIXED_QTY":
        return config.qty, {
            "sizing_mode": config.sizing_mode,
            "equity_before": equity,
            "risk_usdt": 0.0,
            "stop_pct": 0.0,
            "notional": config.qty * close,
        }

    if config.sizing_mode != "EQUITY_COMPOUND":
        if config.sizing_mode != "MARGIN_COMPOUND":
            raise ValueError(f"unknown sizing_mode: {config.sizing_mode}")

        notional = equity * config.margin_per_trade_pct * config.leverage
        qty = int((notional / close) / config.qty_step) * config.qty_step
        if qty < config.min_qty:
            qty = 0.0
        stop_pct = max(atr_pct * config.hard_stop_atr_multiplier, 0.003)
        return qty, {
            "sizing_mode": config.sizing_mode,
            "equity_before": equity,
            "margin_per_trade_pct": config.margin_per_trade_pct,
            "risk_usdt": qty * close * stop_pct,
            "stop_pct": stop_pct,
            "notional": qty * close,
            "margin_usdt": (qty * close) / config.leverage if config.leverage > 0 else 0.0,
        }

    if equity <= 0:
        return 0.0, {
            "sizing_mode": config.sizing_mode,
            "equity_before": equity,
            "risk_usdt": 0.0,
            "stop_pct": 0.0,
            "notional": 0.0,
        }

    sizing = calculate_dynamic_position_size(
        entry_price=close,
        atr_pct=atr_pct,
        config=RiskConfig(
            account_equity=equity,
            risk_per_trade_pct=config.risk_per_trade_pct,
            leverage=config.leverage,
            atr_stop_multiplier=config.hard_stop_atr_multiplier,
            min_qty=config.min_qty,
            qty_step=config.qty_step,
        ),
    )
    return sizing.qty, {
        "sizing_mode": config.sizing_mode,
        "equity_before": equity,
        "risk_usdt": sizing.risk_usdt,
        "stop_pct": sizing.stop_pct,
        "notional": sizing.notional,
        "capped_by_notional": sizing.capped_by_notional,
        "capped_by_hard_loss": sizing.capped_by_hard_loss,
    }


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
    start_idx = max(config.lookback_bars, config.atr_window)
    if len(klines) < start_idx + config.confirm_bars + 2:
        raise ValueError("not enough klines for momentum strategy")

    closes = [float(kline["close"]) for kline in klines]
    tr_prefix = _prefix_sum(_true_ranges(klines, closes))
    signals: list[str] = []
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    equity = config.initial_equity if config.sizing_mode == "EQUITY_COMPOUND" else 0.0
    position: dict[str, Any] | None = None

    for idx in range(start_idx, len(klines)):
        base_close = closes[idx - config.lookback_bars]
        current_close = closes[idx]
        current_atr_pct = _atr_pct(
            tr_prefix=tr_prefix,
            close=current_close,
            idx=idx,
            window=config.atr_window,
        )
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
                qty, sizing_snapshot = _calculate_entry_qty(
                    close=current_close,
                    atr_pct=current_atr_pct,
                    equity=equity,
                    config=config,
                )
                if qty <= 0:
                    continue
                position = {
                    "side": signal,
                    "qty": qty,
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
                        "atr_pct": current_atr_pct,
                        **sizing_snapshot,
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
            qty, sizing_snapshot = _calculate_entry_qty(
                close=current_close,
                atr_pct=current_atr_pct,
                equity=equity,
                config=config,
            )
            if qty <= 0:
                continue
            position = {
                "side": signal,
                "qty": qty,
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
                    "atr_pct": current_atr_pct,
                    **sizing_snapshot,
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
