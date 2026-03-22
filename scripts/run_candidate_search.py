"""
Path: scripts/run_candidate_search.py
說明：Candidate Search v2，從 ACTIVE strategy 產生候選參數組合，逐一跑 backtest 並排序輸出前幾名。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time

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
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)


def _format_weight_summary(weights: dict[str, float], top_n: int = 3) -> str:
    ordered = sorted(
        weights.items(), key=lambda item: float(item[1]), reverse=True)
    top_items = ordered[:top_n]
    return ", ".join(f"{key}={float(value):.4f}" for key, value in top_items)


def _print_weight_summary(params: dict[str, object]) -> None:
    weights = params.get("weights")
    if not isinstance(weights, dict):
        print("weights_summary=NONE")
        return

    long_weights = weights.get("long")
    short_weights = weights.get("short")

    if not isinstance(long_weights, dict) or not isinstance(short_weights, dict):
        print("weights_summary=INVALID")
        return

    print("long_weights_top=" + _format_weight_summary(long_weights))
    print("short_weights_top=" + _format_weight_summary(short_weights))


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _format_elapsed(seconds: float) -> str:
    minutes = int(seconds // 60)
    remain = int(seconds % 60)
    return f"{minutes:02d}:{remain:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate search v2")
    parser.add_argument("--symbol", type=str, default=None, help="例如 BTCUSDT")
    parser.add_argument("--interval", type=str, default=None, help="例如 15m")
    parser.add_argument("--start-date", type=str,
                        required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str,
                        required=True, help="YYYY-MM-DD，不含當日")
    parser.add_argument("--version-code", type=str,
                        default=None, help="不帶則使用 ACTIVE")
    parser.add_argument("--top", type=int, default=10, help="顯示前幾名，預設 10")
    parser.add_argument("--max-candidates", type=int,
                        default=100, help="最多跑幾組 candidate，預設 100")
    parser.add_argument("--progress-step", type=int,
                        default=10, help="每幾組印一次進度，預設 10")
    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise ValueError("--max-candidates 必須大於 0")

    if args.progress_step <= 0:
        raise ValueError("--progress-step 必須大於 0")

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
    all_candidates = generate_param_candidates(base_params=base_params)
    candidates = all_candidates[: args.max_candidates]

    print("candidate search 開始")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"version_code={strategy['version_code']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"all_candidate_count={len(all_candidates)}")
    print(f"run_candidate_count={len(candidates)}")
    print("")

    started_at = time.time()
    results: list[dict[str, object]] = []

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

        score = calculate_candidate_score(metrics)

        row = {
            "rank_score": score,
            "candidate_no": idx,
            "params": candidate_params,
            "metrics": metrics,
        }
        results.append(row)

        if idx % args.progress_step == 0 or idx == len(candidates):
            elapsed = _format_elapsed(time.time() - started_at)
            print(
                f"[progress] {idx}/{len(candidates)} "
                f"elapsed={elapsed} "
                f"latest_score={score:.8f} "
                f"latest_net_pnl={float(metrics['net_pnl']):.8f}"
            )

    results.sort(key=lambda item: float(item["rank_score"]), reverse=True)

    print("")
    print("candidate search v2 完成")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"version_code={strategy['version_code']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"candidate_count={len(results)}")
    print(f"elapsed={_format_elapsed(time.time() - started_at)}")
    print("")

    top_n = min(args.top, len(results))
    for i in range(top_n):
        item = results[i]
        metrics = item["metrics"]
        params = item["params"]

        print(f"===== TOP {i + 1} =====")
        print(f"candidate_no={item['candidate_no']}")
        print(f"rank_score={float(item['rank_score']):.8f}")
        print(f"net_pnl={float(metrics['net_pnl']):.8f}")
        print(f"profit_factor={float(metrics['profit_factor']):.8f}")
        print(f"max_drawdown={float(metrics['max_drawdown']):.8f}")
        print(f"total_trades={int(metrics['total_trades'])}")
        print(f"win_rate={float(metrics['win_rate']):.4f}")
        print(f"mutation_tag={params.get('mutation_tag')}")
        _print_weight_summary(params)
        print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
        print("")


if __name__ == "__main__":
    main()
