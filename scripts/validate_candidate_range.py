"""
Path: scripts/validate_candidate_range.py
說明：用指定 candidate_id 的 params，在更長時間區間做驗證回測。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics
from backtest.replay_engine import run_backtest_replay
from storage.db import connection_scope
from storage.repositories.historical_klines_repo import get_historical_klines_by_range
from storage.repositories.strategy_candidates_repo import get_strategy_candidate_by_id


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate candidate on a longer range")
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    args = parser.parse_args()

    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    with connection_scope() as conn:
        candidate = get_strategy_candidate_by_id(conn, candidate_id=args.candidate_id)
        if candidate is None:
            raise RuntimeError(f"找不到 candidate_id={args.candidate_id}")

        klines = get_historical_klines_by_range(
            conn,
            symbol=str(candidate["symbol"]),
            interval=str(candidate["interval"]),
            start_time=start_time,
            end_time=end_time,
        )

    if len(klines) < 61:
        raise RuntimeError(f"歷史 K 線不足，got={len(klines)}")

    params = dict(candidate["params_json"] or {})

    replay_result = run_backtest_replay(
        klines=klines,
        strategy_version_id=int(candidate["source_strategy_version_id"]),
        symbol=str(candidate["symbol"]),
        interval=str(candidate["interval"]),
        params=params,
    )

    metrics = calculate_backtest_metrics(
        trades=replay_result["trades"],
        equity_curve=replay_result["equity_curve"],
    )

    print("candidate range validation 完成")
    print(f"candidate_id={candidate['candidate_id']}")
    print(f"symbol={candidate['symbol']}")
    print(f"interval={candidate['interval']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"total_trades={metrics['total_trades']}")
    print(f"win_rate={metrics['win_rate']:.4f}")
    print(f"net_pnl={metrics['net_pnl']:.8f}")
    print(f"profit_factor={metrics['profit_factor']:.8f}")
    print(f"max_drawdown={metrics['max_drawdown']:.8f}")


if __name__ == "__main__":
    main()