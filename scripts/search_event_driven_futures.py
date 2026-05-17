"""Search event-driven BTCUSDT futures strategies with realistic sizing.

This script is intentionally separate from the older momentum/evolver path.
It looks for rare, high-intensity market events: sharp dumps, sharp pumps,
and volatility expansion. Every candidate is tested with 100 USDT starting
equity, 20x leverage, fees, slippage, maintenance margin, liquidation, and
compound margin sizing.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics  # noqa: E402
from config.settings import load_settings  # noqa: E402
from storage.db import connection_scope  # noqa: E402
from storage.repositories.historical_klines_repo import get_historical_klines_by_range  # noqa: E402


@dataclass(frozen=True)
class EventConfig:
    family: str
    event_window: int = 8
    trend_window: int = 96
    volume_window: int = 96
    range_window: int = 48
    dump_threshold_pct: float = 0.012
    pump_threshold_pct: float = 0.012
    trend_filter_pct: float = 0.0
    min_volume_ratio: float = 0.0
    min_range_ratio: float = 1.0
    stop_loss_pct: float = 0.006
    take_profit_pct: float = 0.010
    trailing_stop_pct: float = 0.006
    min_hold_bars: int = 1
    max_hold_bars: int = 24
    cooldown_bars: int = 8
    initial_equity: float = 100.0
    leverage: float = 20.0
    margin_per_trade_pct: float = 0.06
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    maintenance_margin_pct: float = 0.004
    liquidation_fee_pct: float = 0.0015
    funding_rate_per_8h: float = 0.0
    min_qty: float = 0.001
    qty_step: float = 0.001


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _load_klines(*, symbol: str, interval: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    with connection_scope() as conn:
        return get_historical_klines_by_range(
            conn,
            symbol=symbol,
            interval=interval,
            start_time=_parse_date_to_utc_start(start_date),
            end_time=_parse_date_to_utc_start(end_date),
        )


def _avg(values: list[float], start: int, end: int) -> float:
    if end <= start:
        return 0.0
    return sum(values[start:end]) / (end - start)


def _entry_price(side: str, price: float, slippage_rate: float) -> float:
    return price * (1 + slippage_rate) if side == "LONG" else price * (1 - slippage_rate)


def _exit_price(side: str, price: float, slippage_rate: float) -> float:
    return price * (1 - slippage_rate) if side == "LONG" else price * (1 + slippage_rate)


def _gross_pnl(side: str, entry_price: float, exit_price: float, qty: float) -> float:
    if side == "LONG":
        return (exit_price - entry_price) * qty
    return (entry_price - exit_price) * qty


def _liquidation_price(side: str, entry_price: float, margin_usdt: float, qty: float, mmr: float) -> float:
    buffer_per_btc = margin_usdt / qty
    if side == "LONG":
        return entry_price + entry_price * mmr - buffer_per_btc
    return entry_price - entry_price * mmr + buffer_per_btc


def _qty_from_margin(*, equity: float, price: float, config: EventConfig) -> tuple[float, float, float]:
    notional = equity * config.margin_per_trade_pct * config.leverage
    qty = int((notional / price) / config.qty_step) * config.qty_step
    if qty < config.min_qty:
        return 0.0, 0.0, 0.0
    notional = qty * price
    margin = notional / config.leverage
    return qty, notional, margin


def _signal_for_idx(
    *,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    idx: int,
    config: EventConfig,
) -> tuple[str, dict[str, float]]:
    event_start = idx - config.event_window
    trend_start = idx - config.trend_window
    volume_start = idx - config.volume_window
    range_start = idx - config.range_window
    if min(event_start, trend_start, volume_start, range_start) < 1:
        return "FLAT", {}

    close = closes[idx]
    event_base = closes[event_start]
    event_return = close / event_base - 1.0
    trend_return = close / closes[trend_start] - 1.0
    avg_volume = _avg(volumes, volume_start, idx)
    volume_ratio = 0.0 if avg_volume <= 0 else volumes[idx] / avg_volume
    bar_range_pct = 0.0 if close <= 0 else (highs[idx] - lows[idx]) / close
    avg_range = _avg([(highs[pos] - lows[pos]) / closes[pos] for pos in range(range_start, idx)], 0, config.range_window)
    range_ratio = 0.0 if avg_range <= 0 else bar_range_pct / avg_range

    if volume_ratio < config.min_volume_ratio or range_ratio < config.min_range_ratio:
        return "FLAT", {
            "event_return": event_return,
            "trend_return": trend_return,
            "volume_ratio": volume_ratio,
            "range_ratio": range_ratio,
        }

    signal = "FLAT"
    if config.family == "dump_reversal":
        if event_return <= -config.dump_threshold_pct and trend_return >= -config.trend_filter_pct:
            signal = "LONG"
    elif config.family == "pump_reversal":
        if event_return >= config.pump_threshold_pct and trend_return <= config.trend_filter_pct:
            signal = "SHORT"
    elif config.family == "volatility_breakout":
        if event_return >= config.pump_threshold_pct and trend_return >= -config.trend_filter_pct:
            signal = "LONG"
        elif event_return <= -config.dump_threshold_pct and trend_return <= config.trend_filter_pct:
            signal = "SHORT"

    return signal, {
        "event_return": event_return,
        "trend_return": trend_return,
        "volume_ratio": volume_ratio,
        "range_ratio": range_ratio,
    }


def _close_trade(
    *,
    position: dict[str, Any],
    exit_kline: dict[str, Any],
    exit_idx: int,
    raw_exit_price: float,
    reason: str,
    config: EventConfig,
) -> dict[str, Any]:
    side = str(position["side"])
    qty = float(position["qty"])
    entry_price = float(position["entry_price"])
    exit_price = _exit_price(side, raw_exit_price, config.slippage_rate)
    gross = _gross_pnl(side, entry_price, exit_price, qty)
    fees = (entry_price + exit_price) * qty * config.fee_rate
    bars_held = exit_idx - int(position["entry_idx"])
    funding_cost = float(position["notional"]) * config.funding_rate_per_8h * (bars_held / 32.0)
    liquidation_fee = float(position["notional"]) * config.liquidation_fee_pct if reason == "LIQUIDATION" else 0.0
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
        "funding_cost": funding_cost,
        "liquidation_fee": liquidation_fee,
        "net_pnl": gross - fees - funding_cost - liquidation_fee,
        "bars_held": bars_held,
        "close_reason": reason,
        "entry_feature_snapshot": dict(position.get("entry_feature_snapshot") or {}),
    }


def run_event_strategy(klines: list[dict[str, Any]], config: EventConfig) -> dict[str, Any]:
    closes = [float(kline["close"]) for kline in klines]
    highs = [float(kline["high"]) for kline in klines]
    lows = [float(kline["low"]) for kline in klines]
    volumes = [float(kline["volume"]) for kline in klines]
    start_idx = max(config.event_window, config.trend_window, config.volume_window, config.range_window) + 1
    if len(klines) < start_idx + 10:
        raise ValueError("not enough klines")

    equity = config.initial_equity
    equity_curve: list[float] = []
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    cooldown_until = 0

    for idx in range(start_idx, len(klines)):
        latest = klines[idx]
        close = closes[idx]
        high = highs[idx]
        low = lows[idx]
        signal, signal_features = _signal_for_idx(
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            idx=idx,
            config=config,
        )

        if position is None:
            if idx < cooldown_until or signal not in {"LONG", "SHORT"} or equity <= 0:
                continue
            qty, notional, margin = _qty_from_margin(equity=equity, price=close, config=config)
            if qty <= 0:
                continue
            entry = _entry_price(signal, close, config.slippage_rate)
            position = {
                "side": signal,
                "qty": qty,
                "notional": notional,
                "margin_usdt": margin,
                "entry_idx": idx,
                "entry_time": latest["close_time"],
                "entry_price": entry,
                "best_price": close,
                "entry_feature_snapshot": {
                    "family": config.family,
                    "equity_before": equity,
                    "margin_usdt": margin,
                    "notional": notional,
                    **signal_features,
                },
            }
            continue

        side = str(position["side"])
        bars_held = idx - int(position["entry_idx"])
        liq = _liquidation_price(
            side,
            float(position["entry_price"]),
            float(position["margin_usdt"]),
            float(position["qty"]),
            config.maintenance_margin_pct,
        )
        reason: str | None = None
        raw_exit: float | None = None
        if side == "LONG":
            position["best_price"] = max(float(position["best_price"]), high)
            trailing = float(position["best_price"]) * (1 - config.trailing_stop_pct)
            stop = float(position["entry_price"]) * (1 - config.stop_loss_pct)
            target = float(position["entry_price"]) * (1 + config.take_profit_pct)
            if low <= liq:
                reason, raw_exit = "LIQUIDATION", liq
            elif low <= stop:
                reason, raw_exit = "STOP_LOSS", stop
            elif high >= target:
                reason, raw_exit = "TAKE_PROFIT", target
            elif bars_held >= config.min_hold_bars and low <= trailing:
                reason, raw_exit = "TRAILING_STOP", trailing
            elif bars_held >= config.max_hold_bars:
                reason, raw_exit = "MAX_HOLD", close
        else:
            position["best_price"] = min(float(position["best_price"]), low)
            trailing = float(position["best_price"]) * (1 + config.trailing_stop_pct)
            stop = float(position["entry_price"]) * (1 + config.stop_loss_pct)
            target = float(position["entry_price"]) * (1 - config.take_profit_pct)
            if high >= liq:
                reason, raw_exit = "LIQUIDATION", liq
            elif high >= stop:
                reason, raw_exit = "STOP_LOSS", stop
            elif low <= target:
                reason, raw_exit = "TAKE_PROFIT", target
            elif bars_held >= config.min_hold_bars and high >= trailing:
                reason, raw_exit = "TRAILING_STOP", trailing
            elif bars_held >= config.max_hold_bars:
                reason, raw_exit = "MAX_HOLD", close

        if reason is None:
            continue

        assert raw_exit is not None
        trade = _close_trade(
            position=position,
            exit_kline=latest,
            exit_idx=idx,
            raw_exit_price=raw_exit,
            reason=reason,
            config=config,
        )
        trades.append(trade)
        equity = max(0.0, equity + float(trade["net_pnl"]))
        equity_curve.append(equity)
        position = None
        cooldown_until = idx + config.cooldown_bars
        if equity <= 0:
            break

    if position is not None:
        trade = _close_trade(
            position=position,
            exit_kline=klines[-1],
            exit_idx=len(klines) - 1,
            raw_exit_price=float(klines[-1]["close"]),
            reason="END_OF_RANGE",
            config=config,
        )
        trades.append(trade)
        equity_curve.append(max(0.0, equity + float(trade["net_pnl"])))

    return {"trades": trades, "equity_curve": equity_curve}


def _metrics(klines: list[dict[str, Any]], config: EventConfig) -> dict[str, Any]:
    result = run_event_strategy(klines, config)
    metrics = calculate_backtest_metrics(trades=result["trades"], equity_curve=result["equity_curve"])
    metrics["final_equity"] = config.initial_equity + float(metrics["net_pnl"])
    metrics["return_pct"] = (float(metrics["final_equity"]) / config.initial_equity - 1.0) * 100.0
    metrics["liquidation_count"] = sum(1 for trade in result["trades"] if trade.get("close_reason") == "LIQUIDATION")
    return metrics


def _candidate_configs(base: EventConfig) -> list[EventConfig]:
    candidates: list[EventConfig] = []
    for family in ["dump_reversal", "pump_reversal", "volatility_breakout"]:
        for event_window in [4, 8, 16, 32]:
            for threshold in [0.006, 0.009, 0.012, 0.018, 0.024, 0.035]:
                for margin in [0.03, 0.05, 0.08, 0.10, 0.12]:
                    for stop in [0.004, 0.006, 0.008, 0.012, 0.016]:
                        for reward in [1.0, 1.5, 2.0, 3.0, 4.0]:
                            candidates.append(
                                EventConfig(
                                    family=family,
                                    event_window=event_window,
                                    dump_threshold_pct=threshold,
                                    pump_threshold_pct=threshold,
                                    trend_filter_pct=0.08,
                                    min_volume_ratio=base.min_volume_ratio,
                                    min_range_ratio=base.min_range_ratio,
                                    stop_loss_pct=stop,
                                    take_profit_pct=stop * reward,
                                    trailing_stop_pct=max(stop, 0.004),
                                    max_hold_bars=base.max_hold_bars,
                                    cooldown_bars=base.cooldown_bars,
                                    margin_per_trade_pct=margin,
                                    initial_equity=base.initial_equity,
                                    leverage=base.leverage,
                                    funding_rate_per_8h=base.funding_rate_per_8h,
                                )
                            )
    return candidates


def _score(full: dict[str, Any], older: dict[str, Any], recent: dict[str, Any]) -> float:
    min_trades = min(full["total_trades"], older["total_trades"], recent["total_trades"])
    if full["liquidation_count"] or older["liquidation_count"] or recent["liquidation_count"]:
        return -1_000_000.0
    if min_trades < 8:
        return -750_000.0 + min_trades
    if full["final_equity"] <= 100 or older["final_equity"] <= 100 or recent["final_equity"] <= 100:
        return -500_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    if full["max_drawdown"] > 35 or older["max_drawdown"] > 30 or recent["max_drawdown"] > 25:
        return -100_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    return (
        float(full["net_pnl"])
        + min(float(older["net_pnl"]), float(recent["net_pnl"])) * 4.0
        + float(full["profit_factor"]) * 15.0
        - float(full["max_drawdown"]) * 1.3
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search event-driven realistic futures candidates")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--initial-equity", type=float, default=100.0)
    parser.add_argument("--leverage", type=float, default=20.0)
    parser.add_argument("--funding-rate-per-8h", type=float, default=0.0)
    parser.add_argument("--min-volume-ratio", type=float, default=0.0)
    parser.add_argument("--min-range-ratio", type=float, default=1.0)
    parser.add_argument("--max-hold-bars", type=int, default=24)
    parser.add_argument("--cooldown-bars", type=int, default=8)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    settings = load_settings()
    symbol = args.symbol or settings.primary_symbol
    interval = args.interval or settings.primary_interval
    ranges = {
        "full": ("2025-05-01", "2026-05-15"),
        "older": ("2025-05-01", "2026-03-01"),
        "recent": ("2026-03-01", "2026-05-15"),
    }
    klines = {
        name: _load_klines(symbol=symbol, interval=interval, start_date=start, end_date=end)
        for name, (start, end) in ranges.items()
    }
    base = EventConfig(
        family="dump_reversal",
        initial_equity=args.initial_equity,
        leverage=args.leverage,
        funding_rate_per_8h=args.funding_rate_per_8h,
        min_volume_ratio=args.min_volume_ratio,
        min_range_ratio=args.min_range_ratio,
        max_hold_bars=args.max_hold_bars,
        cooldown_bars=args.cooldown_bars,
    )
    candidates = _candidate_configs(base)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    scored: list[tuple[float, EventConfig, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for idx, config in enumerate(candidates, start=1):
        full = _metrics(klines["full"], config)
        older = _metrics(klines["older"], config)
        recent = _metrics(klines["recent"], config)
        scored.append((_score(full, older, recent), config, full, older, recent))
        if idx % 100 == 0:
            print(f"[progress] {idx}/{len(candidates)} best_score={max(item[0] for item in scored):.8f}", flush=True)

    scored.sort(key=lambda item: item[0], reverse=True)
    print("event-driven futures search")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"candidate_count={len(candidates)}")
    for rank, (score, config, full, older, recent) in enumerate(scored[: args.top], start=1):
        print(f"----- RANK {rank} -----")
        print(f"score={score:.8f}")
        print(f"config={asdict(config)}")
        for name, metrics in [("full", full), ("older", older), ("recent", recent)]:
            print(
                f"{name}: final_equity={metrics['final_equity']:.8f} "
                f"return_pct={metrics['return_pct']:.4f} net_pnl={metrics['net_pnl']:.8f} "
                f"pf={metrics['profit_factor']:.8f} dd={metrics['max_drawdown']:.8f} "
                f"trades={metrics['total_trades']} liq={metrics['liquidation_count']}"
            )


if __name__ == "__main__":
    main()
