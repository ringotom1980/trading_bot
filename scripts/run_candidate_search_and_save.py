"""
Path: scripts/run_candidate_search_and_save.py
說明：執行 candidate search 並將結果寫入 strategy_candidates。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics
from backtest.replay_engine import run_backtest_replay
from config.settings import load_settings
from evolver.generator import generate_param_candidates
from evolver.scorer import calculate_candidate_score
from storage.db import connection_scope
from storage.repositories.historical_klines_repo import get_historical_klines_by_range
from storage.repositories.strategy_candidates_repo import (
    get_top_strategy_candidates,
    upsert_strategy_candidate,
)
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate search and save v1")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--version-code", type=str, default=None)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    settings = load_settings()
    symbol = args.symbol or settings.primary_symbol
    interval = args.interval or settings.primary_interval
    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    if start_time >= end_time:
        raise ValueError("start-date 必須早於 end-date")

    with connection_scope() as conn:
        if args.version_code:
            strategy = get_strategy_version_by_code(conn, args.version_code)
            if strategy is None:
                raise RuntimeError(f"找不到策略版本：{args.version_code}")
        else:
            strategy = get_active_strategy_version(conn)
            if strategy is None:
                raise RuntimeError("找不到 ACTIVE 策略版本")

        klines = get_historical_klines_by_range(
            conn,
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
        )

    if len(klines) < 61:
        raise RuntimeError(f"歷史 K 線不足，got={len(klines)}")

    base_params = dict(strategy["params_json"] or {})
    candidates = generate_param_candidates(base_params=base_params)

    saved_count = 0

    with connection_scope() as conn:
        for idx, candidate_params in enumerate(candidates, start=1):
            replay_result = run_backtest_replay(
                klines=klines,
                strategy_version_id=int(strategy["strategy_version_id"]),
                symbol=symbol,
                interval=interval,
                params=candidate_params,
            )

            metrics = calculate_backtest_metrics(
                trades=replay_result["trades"],
                equity_curve=replay_result["equity_curve"],
            )

            rank_score = calculate_candidate_score(metrics)

            upsert_strategy_candidate(
                conn,
                source_strategy_version_id=int(strategy["strategy_version_id"]),
                symbol=symbol,
                interval=interval,
                tested_range_start=start_time,
                tested_range_end=end_time,
                candidate_no=idx,
                params=candidate_params,
                metrics=metrics,
                rank_score=rank_score,
                note="candidate search v1",
            )
            saved_count += 1

        top_rows = get_top_strategy_candidates(
            conn,
            source_strategy_version_id=int(strategy["strategy_version_id"]),
            symbol=symbol,
            interval=interval,
            tested_range_start=start_time,
            tested_range_end=end_time,
            limit=args.top,
        )

    print("candidate search and save v1 完成")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"version_code={strategy['version_code']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"candidate_count={len(candidates)}")
    print(f"saved_count={saved_count}")
    print("")

    for idx, row in enumerate(top_rows, start=1):
        metrics = dict(row["metrics_json"] or {})
        params = dict(row["params_json"] or {})

        print(f"===== TOP {idx} =====")
        print(f"candidate_id={row['candidate_id']}")
        print(f"candidate_no={row['candidate_no']}")
        print(f"rank_score={float(row['rank_score']):.8f}")
        print(f"net_pnl={float(metrics.get('net_pnl', 0.0)):.8f}")
        print(f"profit_factor={float(metrics.get('profit_factor', 0.0)):.8f}")
        print(f"max_drawdown={float(metrics.get('max_drawdown', 0.0)):.8f}")
        print(f"total_trades={int(metrics.get('total_trades', 0))}")
        print(f"win_rate={float(metrics.get('win_rate', 0.0)):.4f}")
        print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
        print("")


if __name__ == "__main__":
    main()