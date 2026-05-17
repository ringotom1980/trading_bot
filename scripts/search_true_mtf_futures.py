"""Search true multi-timeframe BTCUSDT futures strategies.

Design:
- 30m bars decide the broad regime and allowed direction.
- 15m bars are the main decision clock.
- 5m bars confirm entry quality near the 15m close.
- 1m bars are optional microstructure filters for recent data.

The model uses 100 USDT starting equity, 20x max leverage, compound margin
sizing, fees, slippage, maintenance margin, and liquidation checks.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
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
class TrueMtfConfig:
    regime_30m_lookback: int = 96
    trend_15m_lookback: int = 96
    pullback_15m_lookback: int = 12
    confirm_5m_lookback: int = 6
    micro_1m_lookback: int = 15
    regime_threshold_pct: float = 0.025
    trend_threshold_pct: float = 0.006
    max_pullback_pct: float = 0.012
    confirm_threshold_pct: float = 0.0015
    max_micro_chase_pct: float = 0.006
    min_taker_buy_ratio_long: float = 0.45
    max_taker_buy_ratio_short: float = 0.55
    atr_15m_window: int = 14
    stop_atr_multiplier: float = 2.2
    take_profit_r: float = 2.0
    trailing_atr_multiplier: float = 2.8
    min_hold_bars: int = 2
    max_hold_bars: int = 96
    cooldown_bars: int = 6
    initial_equity: float = 100.0
    leverage: float = 20.0
    margin_per_trade_pct: float = 0.08
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    maintenance_margin_pct: float = 0.004
    liquidation_fee_pct: float = 0.0015
    min_qty: float = 0.001
    qty_step: float = 0.001
    use_1m_filter: bool = False


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


def _times(klines: list[dict[str, Any]]) -> list[datetime]:
    return [kline["close_time"] for kline in klines]


def _idx_at_or_before(times: list[datetime], value: datetime) -> int | None:
    idx = bisect_right(times, value) - 1
    return idx if idx >= 0 else None


def _pct_change(closes: list[float], idx: int, lookback: int) -> float | None:
    if idx < lookback:
        return None
    base = closes[idx - lookback]
    return None if base == 0 else (closes[idx] - base) / base


def _atr_pct(klines: list[dict[str, Any]], closes: list[float], idx: int, window: int) -> float | None:
    if idx < window:
        return None
    tr_values: list[float] = []
    for pos in range(idx - window + 1, idx + 1):
        high = float(klines[pos]["high"])
        low = float(klines[pos]["low"])
        previous_close = closes[pos - 1]
        tr_values.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    close = closes[idx]
    return None if close == 0 else sum(tr_values) / len(tr_values) / close


def _taker_buy_ratio(kline: dict[str, Any]) -> float:
    volume = float(kline.get("volume") or 0.0)
    taker_buy = float(kline.get("taker_buy_base_volume") or 0.0)
    return 0.5 if volume <= 0 else taker_buy / volume


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


def _qty_from_margin(*, equity: float, price: float, config: TrueMtfConfig) -> tuple[float, float, float]:
    notional = equity * config.margin_per_trade_pct * config.leverage
    qty = int((notional / price) / config.qty_step) * config.qty_step
    if qty < config.min_qty:
        return 0.0, 0.0, 0.0
    notional = qty * price
    margin = notional / config.leverage
    return qty, notional, margin


def _desired_signal(
    *,
    k15: list[dict[str, Any]],
    k30: list[dict[str, Any]],
    k5: list[dict[str, Any]],
    k1: list[dict[str, Any]],
    t30: list[datetime],
    t5: list[datetime],
    t1: list[datetime],
    closes15: list[float],
    closes30: list[float],
    closes5: list[float],
    closes1: list[float],
    idx15: int,
    config: TrueMtfConfig,
) -> tuple[str, dict[str, float]]:
    current_time = k15[idx15]["close_time"]
    idx30 = _idx_at_or_before(t30, current_time)
    idx5 = _idx_at_or_before(t5, current_time)
    idx1 = _idx_at_or_before(t1, current_time) if k1 else None
    if idx30 is None or idx5 is None:
        return "FLAT", {}

    regime = _pct_change(closes30, idx30, config.regime_30m_lookback)
    trend15 = _pct_change(closes15, idx15, config.trend_15m_lookback)
    pullback15 = _pct_change(closes15, idx15, config.pullback_15m_lookback)
    confirm5 = _pct_change(closes5, idx5, config.confirm_5m_lookback)
    if regime is None or trend15 is None or pullback15 is None or confirm5 is None:
        return "FLAT", {}

    micro1 = 0.0
    if config.use_1m_filter:
        if idx1 is None:
            return "FLAT", {}
        maybe_micro = _pct_change(closes1, idx1, config.micro_1m_lookback)
        if maybe_micro is None:
            return "FLAT", {}
        micro1 = maybe_micro

    taker_ratio = _taker_buy_ratio(k15[idx15])
    features = {
        "regime_30m_pct": regime,
        "trend_15m_pct": trend15,
        "pullback_15m_pct": pullback15,
        "confirm_5m_pct": confirm5,
        "micro_1m_pct": micro1,
        "taker_buy_ratio_15m": taker_ratio,
    }

    if (
        regime >= config.regime_threshold_pct
        and trend15 >= config.trend_threshold_pct
        and -config.max_pullback_pct <= pullback15 <= config.max_pullback_pct
        and confirm5 >= config.confirm_threshold_pct
        and micro1 <= config.max_micro_chase_pct
        and taker_ratio >= config.min_taker_buy_ratio_long
    ):
        return "LONG", features

    if (
        regime <= -config.regime_threshold_pct
        and trend15 <= -config.trend_threshold_pct
        and -config.max_pullback_pct <= pullback15 <= config.max_pullback_pct
        and confirm5 <= -config.confirm_threshold_pct
        and micro1 >= -config.max_micro_chase_pct
        and taker_ratio <= config.max_taker_buy_ratio_short
    ):
        return "SHORT", features

    return "FLAT", features


def _close_trade(
    *,
    position: dict[str, Any],
    exit_kline: dict[str, Any],
    exit_idx: int,
    raw_exit_price: float,
    reason: str,
    config: TrueMtfConfig,
) -> dict[str, Any]:
    side = str(position["side"])
    qty = float(position["qty"])
    entry_price = float(position["entry_price"])
    exit_price = _exit_price(side, raw_exit_price, config.slippage_rate)
    gross = _gross_pnl(side, entry_price, exit_price, qty)
    fees = (entry_price + exit_price) * qty * config.fee_rate
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
        "liquidation_fee": liquidation_fee,
        "net_pnl": gross - fees - liquidation_fee,
        "bars_held": exit_idx - int(position["entry_idx"]),
        "close_reason": reason,
        "entry_feature_snapshot": dict(position.get("entry_feature_snapshot") or {}),
    }


def run_true_mtf_strategy(
    *,
    k15: list[dict[str, Any]],
    k30: list[dict[str, Any]],
    k5: list[dict[str, Any]],
    k1: list[dict[str, Any]],
    config: TrueMtfConfig,
) -> dict[str, Any]:
    closes15 = [float(kline["close"]) for kline in k15]
    closes30 = [float(kline["close"]) for kline in k30]
    closes5 = [float(kline["close"]) for kline in k5]
    closes1 = [float(kline["close"]) for kline in k1]
    t30 = _times(k30)
    t5 = _times(k5)
    t1 = _times(k1)
    start_idx = max(config.trend_15m_lookback, config.pullback_15m_lookback, config.atr_15m_window + 1)
    equity = config.initial_equity
    equity_curve: list[float] = []
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    cooldown_until = 0

    for idx in range(start_idx, len(k15)):
        latest = k15[idx]
        close = closes15[idx]
        high = float(latest["high"])
        low = float(latest["low"])
        atr_pct = _atr_pct(k15, closes15, idx, config.atr_15m_window)
        if atr_pct is None:
            continue
        signal, features = _desired_signal(
            k15=k15,
            k30=k30,
            k5=k5,
            k1=k1,
            t30=t30,
            t5=t5,
            t1=t1,
            closes15=closes15,
            closes30=closes30,
            closes5=closes5,
            closes1=closes1,
            idx15=idx,
            config=config,
        )

        if position is None:
            if idx < cooldown_until or signal not in {"LONG", "SHORT"} or equity <= 0:
                continue
            qty, notional, margin = _qty_from_margin(equity=equity, price=close, config=config)
            if qty <= 0:
                continue
            entry = _entry_price(signal, close, config.slippage_rate)
            stop_distance = entry * atr_pct * config.stop_atr_multiplier
            position = {
                "side": signal,
                "qty": qty,
                "notional": notional,
                "margin_usdt": margin,
                "entry_idx": idx,
                "entry_time": latest["close_time"],
                "entry_price": entry,
                "best_price": close,
                "stop_distance": stop_distance,
                "entry_feature_snapshot": {
                    **features,
                    "atr_15m_pct": atr_pct,
                    "equity_before": equity,
                    "margin_usdt": margin,
                    "notional": notional,
                },
            }
            continue

        side = str(position["side"])
        bars_held = idx - int(position["entry_idx"])
        entry = float(position["entry_price"])
        stop_distance = float(position["stop_distance"])
        liq = _liquidation_price(side, entry, float(position["margin_usdt"]), float(position["qty"]), config.maintenance_margin_pct)
        reason: str | None = None
        raw_exit: float | None = None
        if side == "LONG":
            position["best_price"] = max(float(position["best_price"]), high)
            stop = entry - stop_distance
            target = entry + stop_distance * config.take_profit_r
            trailing = float(position["best_price"]) - close * atr_pct * config.trailing_atr_multiplier
            if low <= liq:
                reason, raw_exit = "LIQUIDATION", liq
            elif low <= stop:
                reason, raw_exit = "STOP_LOSS", stop
            elif high >= target:
                reason, raw_exit = "TAKE_PROFIT", target
            elif bars_held >= config.min_hold_bars and low <= trailing:
                reason, raw_exit = "TRAILING_STOP", trailing
            elif bars_held >= config.min_hold_bars and signal == "SHORT":
                reason, raw_exit = "REVERSE_SIGNAL", close
            elif bars_held >= config.max_hold_bars:
                reason, raw_exit = "MAX_HOLD", close
        else:
            position["best_price"] = min(float(position["best_price"]), low)
            stop = entry + stop_distance
            target = entry - stop_distance * config.take_profit_r
            trailing = float(position["best_price"]) + close * atr_pct * config.trailing_atr_multiplier
            if high >= liq:
                reason, raw_exit = "LIQUIDATION", liq
            elif high >= stop:
                reason, raw_exit = "STOP_LOSS", stop
            elif low <= target:
                reason, raw_exit = "TAKE_PROFIT", target
            elif bars_held >= config.min_hold_bars and high >= trailing:
                reason, raw_exit = "TRAILING_STOP", trailing
            elif bars_held >= config.min_hold_bars and signal == "LONG":
                reason, raw_exit = "REVERSE_SIGNAL", close
            elif bars_held >= config.max_hold_bars:
                reason, raw_exit = "MAX_HOLD", close

        if reason is None:
            continue
        assert raw_exit is not None
        trade = _close_trade(position=position, exit_kline=latest, exit_idx=idx, raw_exit_price=raw_exit, reason=reason, config=config)
        trades.append(trade)
        equity = max(0.0, equity + float(trade["net_pnl"]))
        equity_curve.append(equity)
        position = None
        cooldown_until = idx + config.cooldown_bars
        if equity <= 0:
            break

    if position is not None:
        trade = _close_trade(position=position, exit_kline=k15[-1], exit_idx=len(k15) - 1, raw_exit_price=float(k15[-1]["close"]), reason="END_OF_RANGE", config=config)
        trades.append(trade)
        equity_curve.append(max(0.0, equity + float(trade["net_pnl"])))

    return {"trades": trades, "equity_curve": equity_curve}


def _metrics(data: dict[str, list[dict[str, Any]]], config: TrueMtfConfig) -> dict[str, Any]:
    result = run_true_mtf_strategy(k15=data["15m"], k30=data["30m"], k5=data["5m"], k1=data.get("1m", []), config=config)
    metrics = calculate_backtest_metrics(trades=result["trades"], equity_curve=result["equity_curve"])
    metrics["final_equity"] = config.initial_equity + float(metrics["net_pnl"])
    metrics["return_pct"] = (metrics["final_equity"] / config.initial_equity - 1.0) * 100.0
    metrics["liquidation_count"] = sum(1 for trade in result["trades"] if trade.get("close_reason") == "LIQUIDATION")
    return metrics


def _candidate_configs(base: TrueMtfConfig) -> list[TrueMtfConfig]:
    candidates: list[TrueMtfConfig] = []
    for regime_threshold in [0.015, 0.025, 0.04, 0.06]:
        for trend_threshold in [0.003, 0.006, 0.010, 0.015]:
            for confirm_threshold in [0.0005, 0.0015, 0.003, 0.005]:
                for margin in [0.03, 0.05, 0.08, 0.10]:
                    for stop_mult in [1.5, 2.2, 3.0]:
                        candidates.append(
                            TrueMtfConfig(
                                regime_threshold_pct=regime_threshold,
                                trend_threshold_pct=trend_threshold,
                                confirm_threshold_pct=confirm_threshold,
                                margin_per_trade_pct=margin,
                                stop_atr_multiplier=stop_mult,
                                take_profit_r=base.take_profit_r,
                                trailing_atr_multiplier=max(stop_mult * 1.25, 2.0),
                                use_1m_filter=base.use_1m_filter,
                                initial_equity=base.initial_equity,
                                leverage=base.leverage,
                            )
                        )
    return candidates


def _score(full: dict[str, Any], older: dict[str, Any], recent: dict[str, Any]) -> float:
    if full["liquidation_count"] or older["liquidation_count"] or recent["liquidation_count"]:
        return -1_000_000.0
    if min(full["total_trades"], older["total_trades"], recent["total_trades"]) < 3:
        return -750_000.0
    if full["final_equity"] <= 100 or older["final_equity"] <= 100 or recent["final_equity"] <= 100:
        return -500_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    return (
        float(full["net_pnl"])
        + min(float(older["net_pnl"]), float(recent["net_pnl"])) * 4.0
        + float(full["profit_factor"]) * 20.0
        - float(full["max_drawdown"]) * 1.2
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search true MTF futures strategy")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--initial-equity", type=float, default=100.0)
    parser.add_argument("--leverage", type=float, default=20.0)
    parser.add_argument("--use-1m-filter", action="store_true")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    settings = load_settings()
    symbol = args.symbol or settings.primary_symbol
    ranges = {
        "full": ("2025-05-01", "2026-05-15"),
        "older": ("2025-05-01", "2026-03-01"),
        "recent": ("2026-03-01", "2026-05-15"),
    }
    intervals = ["15m", "30m", "5m"]
    if args.use_1m_filter:
        intervals.append("1m")
    data = {
        name: {interval: _load_klines(symbol=symbol, interval=interval, start_date=start, end_date=end) for interval in intervals}
        for name, (start, end) in ranges.items()
    }
    base = TrueMtfConfig(initial_equity=args.initial_equity, leverage=args.leverage, use_1m_filter=args.use_1m_filter)
    candidates = _candidate_configs(base)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    scored: list[tuple[float, TrueMtfConfig, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for idx, config in enumerate(candidates, start=1):
        full = _metrics(data["full"], config)
        older = _metrics(data["older"], config)
        recent = _metrics(data["recent"], config)
        scored.append((_score(full, older, recent), config, full, older, recent))
        if idx % 50 == 0:
            print(f"[progress] {idx}/{len(candidates)} best_score={max(item[0] for item in scored):.8f}", flush=True)

    scored.sort(key=lambda item: item[0], reverse=True)
    print("true MTF futures search")
    print(f"symbol={symbol}")
    print(f"candidate_count={len(candidates)}")
    print(f"use_1m_filter={args.use_1m_filter}")
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
