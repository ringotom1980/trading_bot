"""Dynamic risk sizing for BTCUSDT futures strategies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    account_equity: float
    risk_per_trade_pct: float = 0.005
    max_position_notional_pct: float = 1.0
    leverage: float = 20.0
    min_stop_pct: float = 0.003
    max_stop_pct: float = 0.08
    atr_stop_multiplier: float = 2.5
    hard_max_loss_usdt: float | None = None
    min_qty: float = 0.001
    qty_step: float = 0.001


@dataclass(frozen=True)
class PositionSizingResult:
    qty: float
    notional: float
    stop_pct: float
    risk_usdt: float
    capped_by_notional: bool
    capped_by_hard_loss: bool


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return int(value / step) * step


def clamp_stop_pct(raw_stop_pct: float, config: RiskConfig) -> float:
    return max(config.min_stop_pct, min(config.max_stop_pct, raw_stop_pct))


def calculate_dynamic_position_size(
    *,
    entry_price: float,
    atr_pct: float,
    config: RiskConfig,
) -> PositionSizingResult:
    """Calculate futures quantity from account risk and volatility."""
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if config.account_equity <= 0:
        raise ValueError("account_equity must be positive")
    if config.risk_per_trade_pct <= 0:
        raise ValueError("risk_per_trade_pct must be positive")
    if config.leverage <= 0:
        raise ValueError("leverage must be positive")

    raw_stop_pct = max(float(atr_pct) * config.atr_stop_multiplier, config.min_stop_pct)
    stop_pct = clamp_stop_pct(raw_stop_pct, config)

    risk_usdt = config.account_equity * config.risk_per_trade_pct
    capped_by_hard_loss = False
    if config.hard_max_loss_usdt is not None and risk_usdt > config.hard_max_loss_usdt:
        risk_usdt = config.hard_max_loss_usdt
        capped_by_hard_loss = True

    qty_by_risk = risk_usdt / (entry_price * stop_pct)

    max_margin_notional = config.account_equity * config.max_position_notional_pct * config.leverage
    qty_by_notional = max_margin_notional / entry_price
    capped_by_notional = qty_by_notional < qty_by_risk

    qty = min(qty_by_risk, qty_by_notional)
    qty = _floor_to_step(qty, config.qty_step)
    if qty < config.min_qty:
        qty = 0.0

    notional = qty * entry_price
    effective_risk = notional * stop_pct

    return PositionSizingResult(
        qty=qty,
        notional=notional,
        stop_pct=stop_pct,
        risk_usdt=effective_risk,
        capped_by_notional=capped_by_notional,
        capped_by_hard_loss=capped_by_hard_loss,
    )

