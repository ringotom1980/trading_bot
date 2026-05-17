"""Run market diagnostics and simple baseline strategies."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.baseline_strategies import (  # noqa: E402
    buy_and_hold_baseline,
    channel_breakout_baseline,
    sma_regime_flip_baseline,
)
from backtest.metrics import calculate_backtest_metrics  # noqa: E402
from config.settings import load_settings  # noqa: E402
from storage.db import connection_scope  # noqa: E402
from storage.repositories.historical_klines_repo import get_historical_klines_by_range  # noqa: E402
from strategy.features import calculate_feature_pack  # noqa: E402


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _safe_pct_change(start: float, end: float) -> float:
    if start == 0:
        return 0.0
    return (end - start) / start


def _print_metrics(name: str, result: dict[str, Any]) -> None:
    metrics = calculate_backtest_metrics(
        trades=result["trades"],
        equity_curve=result["equity_curve"],
    )
    print(f"baseline={name}")
    print(f"  total_trades={metrics['total_trades']}")
    print(f"  win_rate={metrics['win_rate']:.4f}")
    print(f"  net_pnl={metrics['net_pnl']:.8f}")
    print(f"  fees={metrics['fees']:.8f}")
    print(f"  profit_factor={metrics['profit_factor']:.8f}")
    print(f"  max_drawdown={metrics['max_drawdown']:.8f}")
    print(f"  expectancy={metrics['expectancy']:.8f}")


def _diagnose_regimes(klines: list[dict[str, Any]], lookback: int = 480) -> dict[str, Any]:
    counts: dict[str, int] = {}
    scores: list[float] = []

    for idx in range(lookback - 1, len(klines)):
        pack = calculate_feature_pack(
            symbol=str(klines[idx]["symbol"]),
            interval=str(klines[idx]["interval"]),
            klines=klines[idx - lookback + 1: idx + 1],
        )
        regime = str(pack.get("regime", "UNKNOWN"))
        counts[regime] = counts.get(regime, 0) + 1
        scores.append(float(pack.get("regime_score", 0.0)))

    avg_score = sum(scores) / len(scores) if scores else 0.0
    return {
        "lookback": lookback,
        "counts": counts,
        "avg_regime_score": avg_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run market diagnostics and baseline comparisons")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
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

    if len(klines) < 481:
        raise RuntimeError(f"not enough klines for diagnostics: got={len(klines)}")

    first_close = float(klines[0]["close"])
    last_close = float(klines[-1]["close"])
    high = max(float(k["high"]) for k in klines)
    low = min(float(k["low"]) for k in klines)
    range_pct = 0.0 if first_close == 0 else (high - low) / first_close
    close_return = _safe_pct_change(first_close, last_close)
    regime_summary = _diagnose_regimes(klines)

    print("market diagnostics")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"first_close={first_close:.8f}")
    print(f"last_close={last_close:.8f}")
    print(f"close_return_pct={close_return * 100:.4f}")
    print(f"high={high:.8f}")
    print(f"low={low:.8f}")
    print(f"range_pct={range_pct * 100:.4f}")
    print(f"regime_lookback={regime_summary['lookback']}")
    print(f"regime_counts={regime_summary['counts']}")
    print(f"avg_regime_score={regime_summary['avg_regime_score']:.6f}")
    print("")

    print("baseline comparison")
    _print_metrics(
        "buy_and_hold_long",
        buy_and_hold_baseline(klines=klines, side="LONG", qty=args.qty),
    )
    _print_metrics(
        "buy_and_hold_short",
        buy_and_hold_baseline(klines=klines, side="SHORT", qty=args.qty),
    )
    _print_metrics(
        "sma60_240_regime_flip",
        sma_regime_flip_baseline(klines=klines, qty=args.qty),
    )
    _print_metrics(
        "channel96_breakout",
        channel_breakout_baseline(klines=klines, qty=args.qty),
    )


if __name__ == "__main__":
    main()

