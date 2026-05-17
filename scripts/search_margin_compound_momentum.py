"""Search momentum parameters with futures margin-compound sizing.

The scoring model is intentionally harsh: a candidate must survive fees,
slippage, liquidation guard, and out-of-sample slices before it is considered
interesting.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics  # noqa: E402
from backtest.momentum_strategy import MomentumStrategyConfig, run_momentum_strategy_replay  # noqa: E402
from config.settings import load_settings  # noqa: E402
from storage.db import connection_scope  # noqa: E402
from storage.repositories.historical_klines_repo import get_historical_klines_by_range  # noqa: E402


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


def _run_metrics(klines: list[dict[str, Any]], config: MomentumStrategyConfig) -> dict[str, Any]:
    result = run_momentum_strategy_replay(klines=klines, config=config)
    metrics = calculate_backtest_metrics(
        trades=result["trades"],
        equity_curve=result["equity_curve"],
    )
    metrics["final_equity"] = config.initial_equity + float(metrics["net_pnl"])
    metrics["return_pct"] = (
        0.0 if config.initial_equity == 0 else (float(metrics["final_equity"]) / config.initial_equity - 1.0) * 100.0
    )
    metrics["liquidation_count"] = sum(1 for trade in result["trades"] if trade.get("close_reason") == "LIQUIDATION")
    return metrics


def _candidate_configs(base: MomentumStrategyConfig) -> list[MomentumStrategyConfig]:
    candidates: list[MomentumStrategyConfig] = []
    for lookback in [960, 1440, 1920, 2880, 3840, 4800]:
        for threshold in [0.015, 0.02, 0.025, 0.03, 0.04, 0.05]:
            for confirm in [24, 48, 72, 96, 144]:
                for min_hold in [96, 192, 384, 768, 1152]:
                    for margin_pct in [0.10, 0.15, 0.20, 0.25, 0.30]:
                        candidates.append(
                            replace(
                                base,
                                lookback_bars=lookback,
                                threshold_pct=threshold,
                                confirm_bars=confirm,
                                min_hold_bars=min_hold,
                                margin_per_trade_pct=margin_pct,
                            )
                        )
    return candidates


def _score(*, full: dict[str, Any], older: dict[str, Any], recent: dict[str, Any]) -> float:
    if full["liquidation_count"] or older["liquidation_count"] or recent["liquidation_count"]:
        return -1_000_000.0
    if full["final_equity"] <= 100 or older["final_equity"] <= 100 or recent["final_equity"] <= 100:
        return -500_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    if full["max_drawdown"] > 35 or older["max_drawdown"] > 35 or recent["max_drawdown"] > 25:
        return -100_000.0 + min(full["net_pnl"], older["net_pnl"], recent["net_pnl"])
    return (
        float(full["net_pnl"])
        + min(float(older["net_pnl"]), float(recent["net_pnl"])) * 3.0
        + float(full["profit_factor"]) * 10.0
        - float(full["max_drawdown"]) * 1.5
        - float(full["liquidation_count"]) * 1000.0
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search futures margin-compound momentum candidates")
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
    klines_by_range = {
        name: _load_klines(symbol=symbol, interval=interval, start_date=start, end_date=end)
        for name, (start, end) in ranges.items()
    }
    base = MomentumStrategyConfig(
        sizing_mode="MARGIN_COMPOUND",
        initial_equity=args.initial_equity,
        leverage=args.leverage,
        funding_rate_per_8h=args.funding_rate_per_8h,
    )
    candidates = _candidate_configs(base)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    scored: list[tuple[float, MomentumStrategyConfig, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for idx, config in enumerate(candidates, start=1):
        full = _run_metrics(klines_by_range["full"], config)
        older = _run_metrics(klines_by_range["older"], config)
        recent = _run_metrics(klines_by_range["recent"], config)
        scored.append((_score(full=full, older=older, recent=recent), config, full, older, recent))
        if idx % 100 == 0:
            best_score = max(item[0] for item in scored)
            print(f"[progress] {idx}/{len(candidates)} best_score={best_score:.8f}")

    scored.sort(key=lambda item: item[0], reverse=True)
    print("margin compound momentum search")
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
