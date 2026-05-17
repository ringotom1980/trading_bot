"""Run adaptive multi-timeframe strategy backtests."""

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

from backtest.adaptive_mtf_strategy import (  # noqa: E402
    AdaptiveMtfStrategyConfig,
    run_adaptive_mtf_strategy_replay,
)
from backtest.metrics import calculate_backtest_metrics  # noqa: E402
from config.settings import load_settings  # noqa: E402
from storage.db import connection_scope  # noqa: E402
from storage.repositories.historical_klines_repo import get_historical_klines_by_range  # noqa: E402


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _load_klines(*, symbol: str, interval: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    start_time = _parse_date_to_utc_start(start_date)
    end_time = _parse_date_to_utc_start(end_date)
    with connection_scope() as conn:
        return get_historical_klines_by_range(
            conn,
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
        )


def _print_metrics(*, label: str, klines: list[dict[str, Any]], config: AdaptiveMtfStrategyConfig) -> dict[str, Any]:
    result = run_adaptive_mtf_strategy_replay(klines=klines, config=config)
    metrics = calculate_backtest_metrics(
        trades=result["trades"],
        equity_curve=result["equity_curve"],
    )
    print(f"[{label}]")
    print(f"kline_count={len(klines)}")
    print(f"total_trades={metrics['total_trades']}")
    print(f"win_rate={metrics['win_rate']:.4f}")
    print(f"gross_pnl={metrics['gross_pnl']:.8f}")
    print(f"fees={metrics['fees']:.8f}")
    print(f"net_pnl={metrics['net_pnl']:.8f}")
    print(f"avg_trade_pnl={metrics['avg_trade_pnl']:.8f}")
    print(f"profit_factor={metrics['profit_factor']:.8f}")
    print(f"max_drawdown={metrics['max_drawdown']:.8f}")
    print(f"expectancy={metrics['expectancy']:.8f}")
    if result["trades"]:
        latest = result["trades"][-1]
        print(
            "last_trade="
            f"{latest['side']} {latest['close_reason']} "
            f"net={float(latest['net_pnl']):.8f} bars={latest['bars_held']}"
        )
    return metrics


def _candidate_configs(base: AdaptiveMtfStrategyConfig) -> list[AdaptiveMtfStrategyConfig]:
    candidates: list[AdaptiveMtfStrategyConfig] = []
    for mid_lookback in [192, 384, 768]:
        for mid_threshold in [0.006, 0.008, 0.012]:
            for confirm_bars in [8, 12, 16]:
                for min_hold in [48, 96, 192]:
                    candidates.append(
                        replace(
                            base,
                            mid_lookback_bars=mid_lookback,
                            mid_threshold_pct=mid_threshold,
                            confirm_bars=confirm_bars,
                            min_hold_bars=min_hold,
                        )
                    )
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Run adaptive MTF strategy backtests")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--start-date", type=str, default="2025-05-01")
    parser.add_argument("--end-date", type=str, default="2026-05-15")
    parser.add_argument("--older-start-date", type=str, default="2025-05-01")
    parser.add_argument("--older-end-date", type=str, default="2026-03-01")
    parser.add_argument("--recent-start-date", type=str, default="2026-03-01")
    parser.add_argument("--recent-end-date", type=str, default="2026-05-15")
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    settings = load_settings()
    symbol = args.symbol or settings.primary_symbol
    interval = args.interval or settings.primary_interval
    base = AdaptiveMtfStrategyConfig()

    print("adaptive MTF strategy backtest")
    print(f"symbol={symbol}")
    print(f"interval={interval}")

    full_klines = _load_klines(
        symbol=symbol,
        interval=interval,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    if args.search:
        scored: list[tuple[float, AdaptiveMtfStrategyConfig, dict[str, Any]]] = []
        for config in _candidate_configs(base):
            result = run_adaptive_mtf_strategy_replay(klines=full_klines, config=config)
            metrics = calculate_backtest_metrics(
                trades=result["trades"],
                equity_curve=result["equity_curve"],
            )
            score = (
                float(metrics["net_pnl"])
                + float(metrics["profit_factor"]) * 20.0
                - float(metrics["max_drawdown"]) * 0.15
                - max(0, 3 - int(metrics["total_trades"])) * 50.0
            )
            scored.append((score, config, metrics))
        scored.sort(key=lambda item: item[0], reverse=True)
        print("[search_top]")
        for rank, (score, config, metrics) in enumerate(scored[: args.top], start=1):
            print(
                f"rank={rank} score={score:.8f} "
                f"net_pnl={metrics['net_pnl']:.8f} pf={metrics['profit_factor']:.8f} "
                f"dd={metrics['max_drawdown']:.8f} trades={metrics['total_trades']} "
                f"config={asdict(config)}"
            )
        base = scored[0][1]

    print(f"config={asdict(base)}")
    _print_metrics(label="full", klines=full_klines, config=base)
    older_klines = _load_klines(
        symbol=symbol,
        interval=interval,
        start_date=args.older_start_date,
        end_date=args.older_end_date,
    )
    _print_metrics(label="older", klines=older_klines, config=base)
    recent_klines = _load_klines(
        symbol=symbol,
        interval=interval,
        start_date=args.recent_start_date,
        end_date=args.recent_end_date,
    )
    _print_metrics(label="recent", klines=recent_klines, config=base)


if __name__ == "__main__":
    main()
