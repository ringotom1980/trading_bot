"""Run long-horizon momentum strategy backtest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run long-horizon momentum strategy backtest")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--lookback-bars", type=int, default=1920)
    parser.add_argument("--threshold-pct", type=float, default=0.03)
    parser.add_argument("--confirm-bars", type=int, default=96)
    parser.add_argument("--min-hold-bars", type=int, default=384)
    parser.add_argument("--qty", type=float, default=0.01)
    args = parser.parse_args()

    settings = load_settings()
    symbol = args.symbol or settings.primary_symbol
    interval = args.interval or settings.primary_interval
    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    with connection_scope() as conn:
        klines = get_historical_klines_by_range(
            conn,
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
        )

    config = MomentumStrategyConfig(
        lookback_bars=args.lookback_bars,
        threshold_pct=args.threshold_pct,
        confirm_bars=args.confirm_bars,
        min_hold_bars=args.min_hold_bars,
        qty=args.qty,
    )
    result = run_momentum_strategy_replay(klines=klines, config=config)
    metrics = calculate_backtest_metrics(
        trades=result["trades"],
        equity_curve=result["equity_curve"],
    )

    print("momentum strategy backtest")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"lookback_bars={config.lookback_bars}")
    print(f"threshold_pct={config.threshold_pct}")
    print(f"confirm_bars={config.confirm_bars}")
    print(f"min_hold_bars={config.min_hold_bars}")
    print(f"qty={config.qty}")
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
        print("last_trade:")
        for key in sorted(result["trades"][-1].keys()):
            print(f"  {key}={result['trades'][-1][key]}")


if __name__ == "__main__":
    main()

