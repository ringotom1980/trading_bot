"""
Path: scripts/inspect_candidate_gate_failures.py
說明：分析 candidate search 為何全部被 gate 擋掉，統計 reject reason 與最接近通過的候選。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics
from backtest.replay_engine import run_backtest_replay
from config.settings import load_settings
from evolver.generator import generate_param_candidates
from evolver.scorer import calculate_candidate_score, evaluate_candidate_gate
from storage.db import connection_scope
from storage.repositories.historical_klines_repo import get_historical_klines_by_range
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _format_elapsed(seconds: float) -> str:
    minutes = int(seconds // 60)
    remain = int(seconds % 60)
    return f"{minutes:02d}:{remain:02d}"


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


def _extract_family_tag(params: dict[str, Any]) -> str:
    mutation_tag = str(params.get("mutation_tag") or "").strip()
    if not mutation_tag:
        return "base"

    known_weight_families = {
        "trend_up",
        "momentum_up",
        "volume_up",
        "trend_momentum_up",
        "trend_only",
        "momentum_only",
        "long_trend_short_momentum",
        "long_momentum_short_trend",
    }

    for family in known_weight_families:
        suffix = f"+{family}"
        if mutation_tag.endswith(suffix):
            return family

    if ":" in mutation_tag:
        field_name = mutation_tag.split(":", 1)[0].strip()
        return f"threshold:{field_name}"

    return mutation_tag


def _print_feature_diagnostics(metrics: dict[str, Any]) -> None:
    diagnostics = dict(metrics.get("feature_diagnostics") or {})
    winners = dict(diagnostics.get("winners") or {})
    losers = dict(diagnostics.get("losers") or {})
    feature_delta = dict(diagnostics.get("feature_delta") or {})

    print("feature_diagnostics:")
    print(f"  winners_count={int(winners.get('count', 0))}")
    print(f"  losers_count={int(losers.get('count', 0))}")
    print(f"  winners_avg_net_pnl={float(winners.get('avg_net_pnl', 0.0)):.8f}")
    print(f"  losers_avg_net_pnl={float(losers.get('avg_net_pnl', 0.0)):.8f}")

    print("  feature_delta_top:")
    ordered = sorted(
        feature_delta.items(),
        key=lambda item: abs(float(item[1])),
        reverse=True,
    )[:8]
    for key, value in ordered:
        print(f"    {key}={float(value):.8f}")


def _summarize_reject_reasons(results: list[dict[str, object]]) -> dict[str, int]:
    summary: dict[str, int] = {}

    for row in results:
        if bool(row.get("is_qualified")):
            continue
        reason = str(row.get("reject_reason") or "UNKNOWN")
        summary[reason] = summary.get(reason, 0) + 1

    return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect candidate gate failures")
    parser.add_argument("--symbol", type=str, default=None, help="例如 BTCUSDT")
    parser.add_argument("--interval", type=str, default=None, help="例如 15m")
    parser.add_argument("--start-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="YYYY-MM-DD，不含當日")
    parser.add_argument("--version-code", type=str, default=None, help="不帶則使用 ACTIVE")
    parser.add_argument("--max-candidates", type=int, default=100, help="最多跑幾組 candidate，預設 100")
    parser.add_argument("--progress-step", type=int, default=10, help="每幾組印一次進度，預設 10")
    parser.add_argument("--show-closest", type=int, default=10, help="顯示最接近通過的前幾名，預設 10")
    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise ValueError("--max-candidates 必須大於 0")
    if args.progress_step <= 0:
        raise ValueError("--progress-step 必須大於 0")
    if args.show_closest <= 0:
        raise ValueError("--show-closest 必須大於 0")

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

    print("inspect candidate gate failures 開始")
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
    raw_results: list[dict[str, object]] = []

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
        is_qualified, reject_reason = evaluate_candidate_gate(metrics)
        score = calculate_candidate_score(metrics)

        raw_results.append(
            {
                "candidate_no": idx,
                "rank_score": score,
                "params": candidate_params,
                "metrics": metrics,
                "is_qualified": is_qualified,
                "reject_reason": reject_reason,
            }
        )

        if idx % args.progress_step == 0 or idx == len(candidates):
            elapsed = _format_elapsed(time.time() - started_at)
            print(
                f"[progress] {idx}/{len(candidates)} "
                f"elapsed={elapsed} "
                f"latest_score={score:.8f} "
                f"latest_net_pnl={float(metrics.get('net_pnl', 0.0)):.8f}"
            )

    qualified_count = sum(1 for row in raw_results if bool(row["is_qualified"]))
    reject_reason_summary = _summarize_reject_reasons(raw_results)
    closest_results = sorted(
        raw_results,
        key=lambda item: float(item["rank_score"]),
        reverse=True,
    )[: args.show_closest]

    print("")
    print("inspect candidate gate failures 完成")
    print(f"raw_candidate_count={len(raw_results)}")
    print(f"qualified_candidate_count={qualified_count}")
    print(f"failed_candidate_count={len(raw_results) - qualified_count}")
    print(f"elapsed={_format_elapsed(time.time() - started_at)}")
    print("")

    print("reject_reason_summary:")
    if reject_reason_summary:
        for reason, count in reject_reason_summary.items():
            print(f"  {reason}={count}")
    else:
        print("  NONE")
    print("")

    print("closest_candidates:")
    for idx, item in enumerate(closest_results, start=1):
        metrics = dict(item["metrics"])
        params = dict(item["params"])

        print(f"----- CLOSEST {idx} -----")
        print(f"candidate_no={item['candidate_no']}")
        print(f"rank_score={float(item['rank_score']):.8f}")
        print(f"is_qualified={bool(item['is_qualified'])}")
        print(f"reject_reason={item.get('reject_reason')}")
        print(f"net_pnl={float(metrics.get('net_pnl', 0.0)):.8f}")
        print(f"gross_pnl={float(metrics.get('gross_pnl', 0.0)):.8f}")
        print(f"profit_factor={float(metrics.get('profit_factor', 0.0)):.8f}")
        print(f"max_drawdown={float(metrics.get('max_drawdown', 0.0)):.8f}")
        print(f"total_trades={int(metrics.get('total_trades', 0))}")
        print(f"win_rate={float(metrics.get('win_rate', 0.0)):.4f}")
        print(f"expectancy={float(metrics.get('expectancy', 0.0)):.8f}")
        print(f"mutation_tag={params.get('mutation_tag')}")
        print(f"family_tag={_extract_family_tag(params)}")
        _print_weight_summary(params)
        _print_feature_diagnostics(metrics)
        print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
        print("")


if __name__ == "__main__":
    main()