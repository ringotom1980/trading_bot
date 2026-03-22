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
import time

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics
from backtest.replay_engine import run_backtest_replay
from config.settings import load_settings
from evolver.generator import generate_param_candidates
from evolver.scorer import calculate_candidate_score
from storage.db import get_connection, connection_scope
from storage.repositories.historical_klines_repo import get_historical_klines_by_range
from storage.repositories.strategy_candidates_repo import (
    get_top_strategy_candidates,
    upsert_strategy_candidate,
)
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)
from storage.repositories.system_events_repo import create_system_event


def _format_weight_summary(weights: dict[str, float], top_n: int = 3) -> str:
    ordered = sorted(weights.items(), key=lambda item: float(item[1]), reverse=True)
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
    parser = argparse.ArgumentParser(description="Run candidate search and save v2")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--version-code", type=str, default=None)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--max-candidates", type=int, default=100, help="最多跑幾組 candidate，預設 100")
    parser.add_argument("--progress-step", type=int, default=10, help="每幾組印一次進度，預設 10")
    parser.add_argument("--commit-step", type=int, default=20, help="每幾組 commit 一次，預設 20")
    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise ValueError("--max-candidates 必須大於 0")

    if args.progress_step <= 0:
        raise ValueError("--progress-step 必須大於 0")

    if args.commit_step <= 0:
        raise ValueError("--commit-step 必須大於 0")

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

    print("candidate search and save 開始")
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
    saved_count = 0

    conn = get_connection()
    top_rows: list[dict[str, object]] = []

    try:
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
                note="candidate search v3 - generator v5 weights",
            )
            saved_count += 1

            if idx % args.commit_step == 0:
                conn.commit()

            if idx % args.progress_step == 0 or idx == len(candidates):
                elapsed = _format_elapsed(time.time() - started_at)
                print(
                    f"[progress] {idx}/{len(candidates)} "
                    f"saved={saved_count} "
                    f"elapsed={elapsed} "
                    f"latest_score={rank_score:.8f} "
                    f"latest_net_pnl={float(metrics['net_pnl']):.8f}"
                )

        conn.commit()

        top_rows = get_top_strategy_candidates(
            conn,
            source_strategy_version_id=int(strategy["strategy_version_id"]),
            symbol=symbol,
            interval=interval,
            tested_range_start=start_time,
            tested_range_end=end_time,
            limit=args.top,
        )

        create_system_event(
            conn,
            event_type="MANUAL_ACTION",
            event_level="INFO",
            source="SYSTEM",
            message="candidate search and save 完成",
            details={
                "source_strategy_version_id": int(strategy["strategy_version_id"]),
                "symbol": symbol,
                "interval": interval,
                "tested_range_start": start_time.isoformat(),
                "tested_range_end": end_time.isoformat(),
                "candidate_count": len(candidates),
                "saved_count": saved_count,
                "top_candidate_id": int(top_rows[0]["candidate_id"]) if top_rows else None,
                "top_rank_score": float(top_rows[0]["rank_score"]) if top_rows else None,
            },
            created_by="run_candidate_search_and_save",
            engine_mode_before="BACKTEST",
            engine_mode_after="BACKTEST",
            trade_mode_before=None,
            trade_mode_after=None,
            trading_state_before="OFF",
            trading_state_after="OFF",
            live_armed_before=False,
            live_armed_after=False,
            strategy_version_before=int(strategy["strategy_version_id"]),
            strategy_version_after=int(strategy["strategy_version_id"]),
        )
        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("")
    print("candidate search and save v2 完成")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"version_code={strategy['version_code']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"candidate_count={len(candidates)}")
    print(f"saved_count={saved_count}")
    print(f"elapsed={_format_elapsed(time.time() - started_at)}")
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
        print(f"mutation_tag={params.get('mutation_tag')}")
        _print_weight_summary(params)
        print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
        print("")


if __name__ == "__main__":
    main()