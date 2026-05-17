"""Search futures strategies gated by market state.

This is the next research branch after plain momentum and simple strategy
families failed under realistic futures constraints. The core idea is to trade
only when the market state agrees with the entry logic.
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
class RegimeStateConfig:
    family: str
    fast_window: int = 96
    slow_window: int = 384
    regime_window: int = 672
    channel_window: int = 192
    atr_window: int = 96
    rsi_window: int = 14
    trend_gap_pct: float = 0.006
    high_vol_atr_pct: float = 0.004
    low_vol_atr_pct: float = 0.0012
    rsi_low: float = 35.0
    rsi_high: float = 65.0
    breakout_buffer_pct: float = 0.0015
    pullback_pct: float = 0.004
    stop_loss_pct: float = 0.012
    take_profit_pct: float = 0.024
    trailing_stop_pct: float = 0.018
    min_hold_bars: int = 4
    max_hold_bars: int = 96
    cooldown_bars: int = 12
    initial_equity: float = 100.0
    leverage: float = 20.0
    margin_per_trade_pct: float = 0.05
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    maintenance_margin_pct: float = 0.004
    liquidation_fee_pct: float = 0.0015
    funding_rate_per_8h: float = 0.0
    min_qty: float = 0.001
    qty_step: float = 0.001


_CACHE: dict[tuple[int, int, int, int, int, int, int], dict[str, list[Any]]] = {}


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


def _prefix(values: list[float]) -> list[float]:
    out = [0.0]
    total = 0.0
    for value in values:
        total += value
        out.append(total)
    return out


def _avg(prefix: list[float], idx: int, window: int) -> float:
    return (prefix[idx + 1] - prefix[idx - window + 1]) / window


def _rolling_max(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(window, len(values)):
        out[idx] = max(values[idx - window : idx])
    return out


def _rolling_min(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(window, len(values)):
        out[idx] = min(values[idx - window : idx])
    return out


def _true_ranges(klines: list[dict[str, Any]], closes: list[float]) -> list[float]:
    out = [0.0]
    for idx in range(1, len(klines)):
        high = float(klines[idx]["high"])
        low = float(klines[idx]["low"])
        prev_close = closes[idx - 1]
        out.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return out


def _rsi_series(closes: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for idx in range(window + 1, len(closes)):
        gains = 0.0
        losses = 0.0
        for pos in range(idx - window + 1, idx + 1):
            diff = closes[pos] - closes[pos - 1]
            if diff >= 0:
                gains += diff
            else:
                losses -= diff
        if losses == 0:
            out[idx] = 100.0
        else:
            rs = gains / losses
            out[idx] = 100.0 - (100.0 / (1.0 + rs))
    return out


def _prepare(klines: list[dict[str, Any]], config: RegimeStateConfig) -> dict[str, list[Any]]:
    key = (
        id(klines),
        config.fast_window,
        config.slow_window,
        config.regime_window,
        config.channel_window,
        config.atr_window,
        config.rsi_window,
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    closes = [float(k["close"]) for k in klines]
    highs = [float(k["high"]) for k in klines]
    lows = [float(k["low"]) for k in klines]
    close_prefix = _prefix(closes)
    tr_prefix = _prefix(_true_ranges(klines, closes))
    fast: list[float | None] = [None] * len(closes)
    slow: list[float | None] = [None] * len(closes)
    regime_ma: list[float | None] = [None] * len(closes)
    atr_pct: list[float | None] = [None] * len(closes)
    for idx in range(config.fast_window, len(closes)):
        fast[idx] = _avg(close_prefix, idx, config.fast_window)
    for idx in range(config.slow_window, len(closes)):
        slow[idx] = _avg(close_prefix, idx, config.slow_window)
    for idx in range(config.regime_window, len(closes)):
        regime_ma[idx] = _avg(close_prefix, idx, config.regime_window)
    for idx in range(config.atr_window, len(closes)):
        atr = _avg(tr_prefix, idx, config.atr_window)
        atr_pct[idx] = 0.0 if closes[idx] == 0 else atr / closes[idx]

    prepared = {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "fast": fast,
        "slow": slow,
        "regime_ma": regime_ma,
        "atr_pct": atr_pct,
        "rsi": _rsi_series(closes, config.rsi_window),
        "channel_high": _rolling_max(highs, config.channel_window),
        "channel_low": _rolling_min(lows, config.channel_window),
    }
    _CACHE[key] = prepared
    return prepared


def _market_state(ind: dict[str, list[Any]], idx: int, config: RegimeStateConfig) -> str:
    close = float(ind["closes"][idx])
    fast = ind["fast"][idx]
    slow = ind["slow"][idx]
    regime_ma = ind["regime_ma"][idx]
    atr_pct = ind["atr_pct"][idx]
    if fast is None or slow is None or regime_ma is None or atr_pct is None or regime_ma == 0:
        return "UNKNOWN"
    gap = (fast - slow) / slow if slow else 0.0
    regime_gap = (close - regime_ma) / regime_ma
    if atr_pct >= config.high_vol_atr_pct:
        return "HIGH_VOL"
    if abs(gap) < config.trend_gap_pct and atr_pct <= config.low_vol_atr_pct:
        return "LOW_VOL_RANGE"
    if gap >= config.trend_gap_pct and regime_gap > 0:
        return "TREND_UP"
    if gap <= -config.trend_gap_pct and regime_gap < 0:
        return "TREND_DOWN"
    return "RANGE"


def _entry_signal(ind: dict[str, list[Any]], idx: int, config: RegimeStateConfig) -> str:
    state = _market_state(ind, idx, config)
    close = float(ind["closes"][idx])
    fast = ind["fast"][idx]
    rsi = ind["rsi"][idx]
    channel_high = ind["channel_high"][idx]
    channel_low = ind["channel_low"][idx]
    if fast is None or rsi is None or channel_high is None or channel_low is None:
        return "FLAT"

    if config.family == "regime_breakout":
        if state == "TREND_UP" and close > channel_high * (1 + config.breakout_buffer_pct):
            return "LONG"
        if state == "TREND_DOWN" and close < channel_low * (1 - config.breakout_buffer_pct):
            return "SHORT"
        return "FLAT"

    if config.family == "regime_pullback":
        if state == "TREND_UP" and close <= fast * (1 - config.pullback_pct) and rsi <= config.rsi_low:
            return "LONG"
        if state == "TREND_DOWN" and close >= fast * (1 + config.pullback_pct) and rsi >= config.rsi_high:
            return "SHORT"
        return "FLAT"

    if config.family == "range_fade":
        if state in {"RANGE", "LOW_VOL_RANGE"} and close <= channel_low * (1 + config.breakout_buffer_pct) and rsi <= config.rsi_low:
            return "LONG"
        if state in {"RANGE", "LOW_VOL_RANGE"} and close >= channel_high * (1 - config.breakout_buffer_pct) and rsi >= config.rsi_high:
            return "SHORT"
        return "FLAT"

    if config.family == "volatility_avoidance_trend":
        if state == "TREND_UP" and rsi > 50 and close > fast:
            return "LONG"
        if state == "TREND_DOWN" and rsi < 50 and close < fast:
            return "SHORT"
        return "FLAT"

    raise ValueError(f"unknown family: {config.family}")


def _entry_price(side: str, price: float, slip: float) -> float:
    return price * (1 + slip) if side == "LONG" else price * (1 - slip)


def _exit_price(side: str, price: float, slip: float) -> float:
    return price * (1 - slip) if side == "LONG" else price * (1 + slip)


def _pnl(side: str, entry: float, exit_: float, qty: float) -> float:
    return (exit_ - entry) * qty if side == "LONG" else (entry - exit_) * qty


def _liq_price(side: str, entry: float, margin: float, qty: float, mmr: float) -> float:
    buffer = margin / qty
    return entry + entry * mmr - buffer if side == "LONG" else entry - entry * mmr + buffer


def _qty(equity: float, price: float, config: RegimeStateConfig) -> tuple[float, float, float]:
    notional = equity * config.margin_per_trade_pct * config.leverage
    qty = int((notional / price) / config.qty_step) * config.qty_step
    if qty < config.min_qty:
        return 0.0, 0.0, 0.0
    notional = qty * price
    margin = notional / config.leverage
    return qty, notional, margin


def _close(position: dict[str, Any], kline: dict[str, Any], idx: int, raw_price: float, reason: str, config: RegimeStateConfig) -> dict[str, Any]:
    side = str(position["side"])
    qty = float(position["qty"])
    entry = float(position["entry_price"])
    exit_ = _exit_price(side, raw_price, config.slippage_rate)
    gross = _pnl(side, entry, exit_, qty)
    fees = (entry + exit_) * qty * config.fee_rate
    bars = idx - int(position["entry_idx"])
    funding = float(position["notional"]) * config.funding_rate_per_8h * (bars / 32.0)
    liq_fee = float(position["notional"]) * config.liquidation_fee_pct if reason == "LIQUIDATION" else 0.0
    return {
        "symbol": kline["symbol"],
        "interval": kline["interval"],
        "side": side,
        "entry_time": position["entry_time"],
        "exit_time": kline["close_time"],
        "entry_price": entry,
        "exit_price": exit_,
        "qty": qty,
        "gross_pnl": gross,
        "fees": fees,
        "funding_cost": funding,
        "liquidation_fee": liq_fee,
        "net_pnl": gross - fees - funding - liq_fee,
        "bars_held": bars,
        "close_reason": reason,
        "entry_feature_snapshot": dict(position.get("entry_feature_snapshot") or {}),
    }


def run_strategy(klines: list[dict[str, Any]], config: RegimeStateConfig) -> dict[str, Any]:
    start = max(config.slow_window, config.regime_window, config.channel_window, config.atr_window, config.rsi_window + 1)
    if len(klines) < start + 10:
        raise ValueError("not enough klines")
    ind = _prepare(klines, config)
    equity = config.initial_equity
    trades: list[dict[str, Any]] = []
    curve: list[float] = []
    position: dict[str, Any] | None = None
    cooldown_until = 0

    for idx in range(start, len(klines)):
        latest = klines[idx]
        close = float(latest["close"])
        high = float(latest["high"])
        low = float(latest["low"])
        signal = _entry_signal(ind, idx, config)
        state = _market_state(ind, idx, config)

        if position is None:
            if idx < cooldown_until or signal not in {"LONG", "SHORT"} or equity <= 0:
                continue
            qty, notional, margin = _qty(equity, close, config)
            if qty <= 0:
                continue
            entry = _entry_price(signal, close, config.slippage_rate)
            position = {
                "side": signal,
                "qty": qty,
                "notional": notional,
                "margin": margin,
                "entry_price": entry,
                "entry_idx": idx,
                "entry_time": latest["close_time"],
                "best_price": close,
                "entry_feature_snapshot": {
                    "family": config.family,
                    "state": state,
                    "equity_before": equity,
                    "notional": notional,
                    "margin": margin,
                },
            }
            continue

        side = str(position["side"])
        bars = idx - int(position["entry_idx"])
        liq = _liq_price(side, float(position["entry_price"]), float(position["margin"]), float(position["qty"]), config.maintenance_margin_pct)
        reason: str | None = None
        raw: float | None = None

        if side == "LONG":
            position["best_price"] = max(float(position["best_price"]), high)
            stop = float(position["entry_price"]) * (1 - config.stop_loss_pct)
            target = float(position["entry_price"]) * (1 + config.take_profit_pct)
            trail = float(position["best_price"]) * (1 - config.trailing_stop_pct)
            if low <= liq:
                reason, raw = "LIQUIDATION", liq
            elif low <= stop:
                reason, raw = "STOP_LOSS", stop
            elif high >= target:
                reason, raw = "TAKE_PROFIT", target
            elif bars >= config.min_hold_bars and low <= trail:
                reason, raw = "TRAILING_STOP", trail
            elif bars >= config.max_hold_bars:
                reason, raw = "MAX_HOLD", close
        else:
            position["best_price"] = min(float(position["best_price"]), low)
            stop = float(position["entry_price"]) * (1 + config.stop_loss_pct)
            target = float(position["entry_price"]) * (1 - config.take_profit_pct)
            trail = float(position["best_price"]) * (1 + config.trailing_stop_pct)
            if high >= liq:
                reason, raw = "LIQUIDATION", liq
            elif high >= stop:
                reason, raw = "STOP_LOSS", stop
            elif low <= target:
                reason, raw = "TAKE_PROFIT", target
            elif bars >= config.min_hold_bars and high >= trail:
                reason, raw = "TRAILING_STOP", trail
            elif bars >= config.max_hold_bars:
                reason, raw = "MAX_HOLD", close

        if reason is None:
            continue
        assert raw is not None
        trade = _close(position, latest, idx, raw, reason, config)
        trades.append(trade)
        equity = max(0.0, equity + float(trade["net_pnl"]))
        curve.append(equity)
        position = None
        cooldown_until = idx + config.cooldown_bars
        if equity <= 0:
            break

    if position is not None:
        trade = _close(position, klines[-1], len(klines) - 1, float(klines[-1]["close"]), "END_OF_RANGE", config)
        trades.append(trade)
        curve.append(max(0.0, equity + float(trade["net_pnl"])))
    return {"trades": trades, "equity_curve": curve}


def _metrics(klines: list[dict[str, Any]], config: RegimeStateConfig) -> dict[str, Any]:
    result = run_strategy(klines, config)
    metrics = calculate_backtest_metrics(trades=result["trades"], equity_curve=result["equity_curve"])
    metrics["final_equity"] = config.initial_equity + float(metrics["net_pnl"])
    metrics["return_pct"] = (float(metrics["final_equity"]) / config.initial_equity - 1.0) * 100.0
    metrics["liquidation_count"] = sum(1 for trade in result["trades"] if trade.get("close_reason") == "LIQUIDATION")
    return metrics


def _configs(base: RegimeStateConfig) -> list[RegimeStateConfig]:
    configs: list[RegimeStateConfig] = []
    for family in ["regime_breakout", "regime_pullback", "range_fade", "volatility_avoidance_trend"]:
        for margin in [0.03, 0.05, 0.08, 0.10]:
            for trend_gap in [0.004, 0.006, 0.010]:
                for stop in [0.008, 0.012, 0.018]:
                    for take in [0.012, 0.02, 0.03, 0.045]:
                        configs.append(
                            RegimeStateConfig(
                                family=family,
                                margin_per_trade_pct=margin,
                                trend_gap_pct=trend_gap,
                                stop_loss_pct=stop,
                                take_profit_pct=take,
                                trailing_stop_pct=max(stop * 1.5, 0.012),
                                initial_equity=base.initial_equity,
                                leverage=base.leverage,
                                funding_rate_per_8h=base.funding_rate_per_8h,
                            )
                        )
    return configs


def _score(full: dict[str, Any], older: dict[str, Any], recent: dict[str, Any]) -> float:
    if full["liquidation_count"] or older["liquidation_count"] or recent["liquidation_count"]:
        return -1_000_000.0
    if full["final_equity"] <= 100 or older["final_equity"] <= 100 or recent["final_equity"] <= 100:
        return -500_000.0 + min(float(full["net_pnl"]), float(older["net_pnl"]), float(recent["net_pnl"]))
    if full["max_drawdown"] > 25 or older["max_drawdown"] > 25 or recent["max_drawdown"] > 18:
        return -100_000.0 + min(float(full["net_pnl"]), float(older["net_pnl"]), float(recent["net_pnl"]))
    return (
        float(full["net_pnl"])
        + min(float(older["net_pnl"]), float(recent["net_pnl"])) * 3
        + float(full["profit_factor"]) * 15
        - float(full["max_drawdown"]) * 1.5
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search market-state gated futures strategies")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--initial-equity", type=float, default=100.0)
    parser.add_argument("--leverage", type=float, default=20.0)
    parser.add_argument("--funding-rate-per-8h", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top", type=int, default=20)
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
    base = RegimeStateConfig(
        family="regime_breakout",
        initial_equity=args.initial_equity,
        leverage=args.leverage,
        funding_rate_per_8h=args.funding_rate_per_8h,
    )
    configs = _configs(base)
    if args.limit is not None:
        configs = configs[: args.limit]
    scored: list[tuple[float, RegimeStateConfig, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for idx, config in enumerate(configs, start=1):
        full = _metrics(klines["full"], config)
        older = _metrics(klines["older"], config)
        recent = _metrics(klines["recent"], config)
        scored.append((_score(full, older, recent), config, full, older, recent))
        if idx % 100 == 0:
            print(f"[progress] {idx}/{len(configs)} best_score={max(item[0] for item in scored):.8f}")
    scored.sort(key=lambda item: item[0], reverse=True)
    print("regime state futures search")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"candidate_count={len(configs)}")
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
