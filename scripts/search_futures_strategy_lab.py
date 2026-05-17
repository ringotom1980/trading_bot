"""Search realistic BTCUSDT futures strategies beyond plain momentum.

This lab tests a small set of practical strategy families using the same
futures constraints we care about for deployment: 100 USDT starting equity,
20x leverage, margin sizing, fees, slippage, maintenance margin, liquidation,
and no negative equity.
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


_INDICATOR_CACHE: dict[tuple[int, int, int, int, int], dict[str, list[Any]]] = {}


@dataclass(frozen=True)
class LabConfig:
    family: str
    fast_window: int = 96
    slow_window: int = 384
    channel_window: int = 96
    rsi_window: int = 14
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    pullback_pct: float = 0.006
    breakout_buffer_pct: float = 0.001
    stop_loss_pct: float = 0.015
    take_profit_pct: float = 0.03
    trailing_stop_pct: float = 0.02
    min_hold_bars: int = 4
    max_hold_bars: int = 96
    cooldown_bars: int = 8
    initial_equity: float = 100.0
    leverage: float = 20.0
    margin_per_trade_pct: float = 0.15
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


def _prefix_sum(values: list[float]) -> list[float]:
    prefix = [0.0]
    total = 0.0
    for value in values:
        total += value
        prefix.append(total)
    return prefix


def _window_avg(prefix: list[float], *, idx: int, window: int) -> float:
    return (prefix[idx + 1] - prefix[idx - window + 1]) / window


def _rsi(closes: list[float], *, idx: int, window: int) -> float:
    gains = 0.0
    losses = 0.0
    for pos in range(idx - window + 1, idx + 1):
        diff = closes[pos] - closes[pos - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def _rolling_max(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for idx in range(window, len(values)):
        result[idx] = max(values[idx - window : idx])
    return result


def _rolling_min(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for idx in range(window, len(values)):
        result[idx] = min(values[idx - window : idx])
    return result


def _prepare_indicators(klines: list[dict[str, Any]], config: LabConfig) -> dict[str, list[Any]]:
    cache_key = (
        id(klines),
        config.fast_window,
        config.slow_window,
        config.channel_window,
        config.rsi_window,
    )
    cached = _INDICATOR_CACHE.get(cache_key)
    if cached is not None:
        return cached

    closes = [float(kline["close"]) for kline in klines]
    highs = [float(kline["high"]) for kline in klines]
    lows = [float(kline["low"]) for kline in klines]
    close_prefix = _prefix_sum(closes)
    fast: list[float | None] = [None] * len(closes)
    slow: list[float | None] = [None] * len(closes)
    rsi_values: list[float | None] = [None] * len(closes)

    for idx in range(config.fast_window, len(closes)):
        fast[idx] = _window_avg(close_prefix, idx=idx, window=config.fast_window)
    for idx in range(config.slow_window, len(closes)):
        slow[idx] = _window_avg(close_prefix, idx=idx, window=config.slow_window)
    for idx in range(config.rsi_window + 1, len(closes)):
        rsi_values[idx] = _rsi(closes, idx=idx, window=config.rsi_window)

    prepared = {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "fast": fast,
        "slow": slow,
        "rsi": rsi_values,
        "channel_high": _rolling_max(highs, config.channel_window),
        "channel_low": _rolling_min(lows, config.channel_window),
    }
    _INDICATOR_CACHE[cache_key] = prepared
    return prepared


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


def _qty_from_margin(*, equity: float, price: float, config: LabConfig) -> tuple[float, float, float]:
    notional = equity * config.margin_per_trade_pct * config.leverage
    qty = int((notional / price) / config.qty_step) * config.qty_step
    if qty < config.min_qty:
        return 0.0, 0.0, 0.0
    notional = qty * price
    margin = notional / config.leverage
    return qty, notional, margin


def _signal_for_idx(
    *,
    indicators: dict[str, list[Any]],
    idx: int,
    config: LabConfig,
) -> str:
    closes = indicators["closes"]
    close = closes[idx]
    fast = indicators["fast"][idx]
    slow = indicators["slow"][idx]
    channel_high = indicators["channel_high"][idx]
    channel_low = indicators["channel_low"][idx]
    rsi = indicators["rsi"][idx]
    if fast is None or slow is None or channel_high is None or channel_low is None or rsi is None:
        return "FLAT"

    if config.family == "trend_pullback":
        trend_up = fast > slow
        trend_down = fast < slow
        if trend_up and close <= fast * (1 - config.pullback_pct) and rsi <= config.rsi_low:
            return "LONG"
        if trend_down and close >= fast * (1 + config.pullback_pct) and rsi >= config.rsi_high:
            return "SHORT"
        return "FLAT"

    if config.family == "range_reversion":
        range_width_pct = (channel_high - channel_low) / close if close else 0.0
        trend_gap = abs(fast - slow) / slow if slow else 0.0
        if trend_gap > 0.012 or range_width_pct < 0.01:
            return "FLAT"
        if close <= channel_low * (1 + config.breakout_buffer_pct) and rsi <= config.rsi_low:
            return "LONG"
        if close >= channel_high * (1 - config.breakout_buffer_pct) and rsi >= config.rsi_high:
            return "SHORT"
        return "FLAT"

    if config.family == "channel_breakout":
        if fast > slow and close > channel_high * (1 + config.breakout_buffer_pct):
            return "LONG"
        if fast < slow and close < channel_low * (1 - config.breakout_buffer_pct):
            return "SHORT"
        return "FLAT"

    raise ValueError(f"unknown family: {config.family}")


def _close_trade(
    *,
    position: dict[str, Any],
    exit_kline: dict[str, Any],
    exit_idx: int,
    raw_exit_price: float,
    reason: str,
    config: LabConfig,
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


def run_lab_strategy(klines: list[dict[str, Any]], config: LabConfig) -> dict[str, Any]:
    start_idx = max(config.slow_window, config.channel_window, config.rsi_window + 1)
    if len(klines) < start_idx + 10:
        raise ValueError("not enough klines")

    indicators = _prepare_indicators(klines, config)
    closes = indicators["closes"]
    equity = config.initial_equity
    equity_curve: list[float] = []
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    cooldown_until = 0

    for idx in range(start_idx, len(klines)):
        latest = klines[idx]
        close = closes[idx]
        high = float(latest["high"])
        low = float(latest["low"])
        signal = _signal_for_idx(
            indicators=indicators,
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
                    "signal": signal,
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


def _metrics(klines: list[dict[str, Any]], config: LabConfig) -> dict[str, Any]:
    result = run_lab_strategy(klines, config)
    metrics = calculate_backtest_metrics(trades=result["trades"], equity_curve=result["equity_curve"])
    metrics["final_equity"] = config.initial_equity + float(metrics["net_pnl"])
    metrics["return_pct"] = (float(metrics["final_equity"]) / config.initial_equity - 1.0) * 100.0
    metrics["liquidation_count"] = sum(1 for trade in result["trades"] if trade.get("close_reason") == "LIQUIDATION")
    return metrics


def _candidate_configs(base: LabConfig) -> list[LabConfig]:
    candidates: list[LabConfig] = []
    for family in ["trend_pullback", "range_reversion", "channel_breakout"]:
        for margin in [0.05, 0.08, 0.10, 0.12, 0.15]:
            for stop in [0.008, 0.012, 0.016, 0.024]:
                for take in [0.012, 0.018, 0.03, 0.045, 0.06]:
                    for max_hold in [32, 64, 96, 192, 384]:
                        candidates.append(
                            LabConfig(
                                family=family,
                                margin_per_trade_pct=margin,
                                stop_loss_pct=stop,
                                take_profit_pct=take,
                                trailing_stop_pct=max(stop * 1.5, 0.012),
                                max_hold_bars=max_hold,
                                initial_equity=base.initial_equity,
                                leverage=base.leverage,
                                funding_rate_per_8h=base.funding_rate_per_8h,
                            )
                        )
    return candidates


def _score(full: dict[str, Any], older: dict[str, Any], recent: dict[str, Any]) -> float:
    if full["liquidation_count"] or older["liquidation_count"] or recent["liquidation_count"]:
        return -1_000_000.0
    if full["final_equity"] <= 100 or older["final_equity"] <= 100 or recent["final_equity"] <= 100:
        return -500_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    if full["max_drawdown"] > 30 or older["max_drawdown"] > 30 or recent["max_drawdown"] > 20:
        return -100_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    return (
        float(full["net_pnl"])
        + min(float(older["net_pnl"]), float(recent["net_pnl"])) * 3.0
        + float(full["profit_factor"]) * 12.0
        - float(full["max_drawdown"]) * 1.2
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search realistic futures strategy families")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--initial-equity", type=float, default=100.0)
    parser.add_argument("--leverage", type=float, default=20.0)
    parser.add_argument("--funding-rate-per-8h", type=float, default=0.0)
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
    base = LabConfig(
        family="trend_pullback",
        initial_equity=args.initial_equity,
        leverage=args.leverage,
        funding_rate_per_8h=args.funding_rate_per_8h,
    )
    candidates = _candidate_configs(base)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    scored: list[tuple[float, LabConfig, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for idx, config in enumerate(candidates, start=1):
        full = _metrics(klines["full"], config)
        older = _metrics(klines["older"], config)
        recent = _metrics(klines["recent"], config)
        scored.append((_score(full, older, recent), config, full, older, recent))
        if idx % 100 == 0:
            print(f"[progress] {idx}/{len(candidates)} best_score={max(item[0] for item in scored):.8f}")

    scored.sort(key=lambda item: item[0], reverse=True)
    print("futures strategy lab search")
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
