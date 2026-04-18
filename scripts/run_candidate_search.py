"""
Path: scripts/run_candidate_search.py
說明：Candidate Search v3，從 ACTIVE strategy 產生候選參數組合，逐一跑 backtest、做行為去重並排序輸出前幾名。
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
from storage.repositories.search_space_config_repo import get_active_search_space_config
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)


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


def _build_behavior_fingerprint(metrics: dict[str, Any]) -> str:
    """
    功能：建立 candidate 行為指紋，用於去除回測結果幾乎相同的候選。
    說明：
        - total_trades 直接取整數
        - 其餘數值做適度 round，避免極小數差異造成無效分裂
    """
    payload = {
        "total_trades": int(metrics.get("total_trades", 0)),
        "net_pnl": round(float(metrics.get("net_pnl", 0.0)), 4),
        "profit_factor": round(float(metrics.get("profit_factor", 0.0)), 4),
        "max_drawdown": round(float(metrics.get("max_drawdown", 0.0)), 4),
        "win_rate": round(float(metrics.get("win_rate", 0.0)), 4),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _dedupe_results_by_behavior(results: list[dict[str, object]]) -> list[dict[str, object]]:
    """
    功能：依回測行為去重，只保留同一行為指紋中 rank_score 最好的 candidate。
    """
    best_by_fp: dict[str, dict[str, object]] = {}

    for row in results:
        metrics = dict(row["metrics"])
        fp = _build_behavior_fingerprint(metrics)
        existing = best_by_fp.get(fp)

        if existing is None:
            best_by_fp[fp] = row
            continue

        current_score = float(row["rank_score"])
        existing_score = float(existing["rank_score"])

        if current_score > existing_score:
            best_by_fp[fp] = row
            continue

        if current_score == existing_score and int(row["candidate_no"]) < int(existing["candidate_no"]):
            best_by_fp[fp] = row

    deduped = list(best_by_fp.values())
    deduped.sort(key=lambda item: (float(item["rank_score"]), -int(item["candidate_no"])), reverse=True)
    return deduped


def _extract_family_tag(params: dict[str, Any]) -> str:
    """
    功能：從 mutation_tag 萃出 family，用來限制同一家族的候選數量。
    規則：
        - threshold+weight 組合時，以 weight family 為主
          例如：reverse_gap:-0.02+momentum_only -> momentum_only
        - 純 threshold 變化時，用 threshold:<field>
          例如：max_bars_hold:+12 -> threshold:max_bars_hold
        - 純 weight mutation 時，直接回傳 mutation_tag
          例如：momentum_only -> momentum_only
        - 沒有 mutation_tag 時，視為 base
    """
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

    # 先判斷是不是「threshold + weight」組合
    for family in known_weight_families:
        suffix = f"+{family}"
        if mutation_tag.endswith(suffix):
            return family

    # 純 threshold mutation
    if ":" in mutation_tag:
        field_name = mutation_tag.split(":", 1)[0].strip()
        return f"threshold:{field_name}"

    # 純 weight mutation
    return mutation_tag


def _apply_family_diversity_cap(
    results: list[dict[str, object]],
    *,
    per_family_limit: int,
) -> list[dict[str, object]]:
    """
    功能：限制同一 family 最多保留 N 個 candidate，增加候選多樣性。
    """
    if per_family_limit <= 0:
        return results

    selected: list[dict[str, object]] = []
    family_counts: dict[str, int] = {}

    for row in results:
        params = dict(row["params"])
        family = _extract_family_tag(params)
        used = family_counts.get(family, 0)

        if used >= per_family_limit:
            continue

        selected.append(row)
        family_counts[family] = used + 1

    return selected


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
    print(f"  winners_avg_bars_held={float(winners.get('avg_bars_held', 0.0)):.4f}")
    print(f"  losers_avg_bars_held={float(losers.get('avg_bars_held', 0.0)):.4f}")
    print(f"  winners_avg_entry_long_score={float(winners.get('avg_entry_long_score', 0.0)):.8f}")
    print(f"  losers_avg_entry_long_score={float(losers.get('avg_entry_long_score', 0.0)):.8f}")
    print(f"  winners_avg_entry_short_score={float(winners.get('avg_entry_short_score', 0.0)):.8f}")
    print(f"  losers_avg_entry_short_score={float(losers.get('avg_entry_short_score', 0.0)):.8f}")

    print("  feature_delta_top:")
    ordered = sorted(
        feature_delta.items(),
        key=lambda item: abs(float(item[1])),
        reverse=True,
    )[:8]
    for key, value in ordered:
        print(f"    {key}={float(value):.8f}")

    print("  winner_regime_counts=" + json.dumps(winners.get("regime_counts", {}), ensure_ascii=False, sort_keys=True))
    print("  loser_regime_counts=" + json.dumps(losers.get("regime_counts", {}), ensure_ascii=False, sort_keys=True))


def _summarize_reject_reasons(results: list[dict[str, object]]) -> dict[str, int]:
    """
    功能：統計未通過 gate 的 reject_reason 數量。
    """
    summary: dict[str, int] = {}

    for row in results:
        if bool(row.get("is_qualified")):
            continue

        reason = str(row.get("reject_reason") or "UNKNOWN")
        summary[reason] = summary.get(reason, 0) + 1

    return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate search v3")
    parser.add_argument("--symbol", type=str, default=None, help="例如 BTCUSDT")
    parser.add_argument("--interval", type=str, default=None, help="例如 15m")
    parser.add_argument("--start-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="YYYY-MM-DD，不含當日")
    parser.add_argument("--version-code", type=str, default=None, help="不帶則使用 ACTIVE")
    parser.add_argument("--top", type=int, default=10, help="顯示前幾名，預設 10")
    parser.add_argument("--max-candidates", type=int, default=100, help="最多跑幾組 candidate，預設 100")
    parser.add_argument("--progress-step", type=int, default=10, help="每幾組印一次進度，預設 10")
    parser.add_argument("--per-family-limit", type=int, default=2, help="同一 family 最多保留幾個 candidate，預設 2")
    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise ValueError("--max-candidates 必須大於 0")

    if args.progress_step <= 0:
        raise ValueError("--progress-step 必須大於 0")
    
    if args.per_family_limit <= 0:
        raise ValueError("--per-family-limit 必須大於 0")

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
        scope_key = f"{symbol}:{interval}"
        active_search_space = get_active_search_space_config(
            conn,
            scope_key=scope_key,
        )

    if len(klines) < 61:
        raise RuntimeError(f"歷史 K 線不足，got={len(klines)}")

    base_params = dict(strategy["params_json"] or {})
    search_space = active_search_space["config_json"] if active_search_space else None
    all_candidates = generate_param_candidates(
        base_params=base_params,
        search_space=search_space,
    )
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
    print(f"scope_key={scope_key}")
    print(f"active_search_space_config_id={active_search_space['config_id'] if active_search_space else None}")
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

        row = {
            "rank_score": score,
            "candidate_no": idx,
            "params": candidate_params,
            "metrics": metrics,
            "is_qualified": is_qualified,
            "reject_reason": reject_reason,
        }
        raw_results.append(row)

        if idx % args.progress_step == 0 or idx == len(candidates):
            elapsed = _format_elapsed(time.time() - started_at)
            print(
                f"[progress] {idx}/{len(candidates)} "
                f"elapsed={elapsed} "
                f"latest_score={score:.8f} "
                f"latest_net_pnl={float(metrics['net_pnl']):.8f}"
            )

    qualified_results = [row for row in raw_results if bool(row["is_qualified"])]
    reject_reason_summary = _summarize_reject_reasons(raw_results)
    deduped_results = _dedupe_results_by_behavior(qualified_results)
    deduped_results.sort(key=lambda item: float(item["rank_score"]), reverse=True)
    diversified_results = _apply_family_diversity_cap(
        deduped_results,
        per_family_limit=args.per_family_limit,
    )

    print("")
    print("candidate search v3 完成")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"version_code={strategy['version_code']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"raw_candidate_count={len(raw_results)}")
    print(f"qualified_candidate_count={len(qualified_results)}")
    print(f"deduped_candidate_count={len(deduped_results)}")
    print(f"diversified_candidate_count={len(diversified_results)}")
    print(f"per_family_limit={args.per_family_limit}")
    print(f"elapsed={_format_elapsed(time.time() - started_at)}")
    print("")

    print("reject_reason_summary:")
    if reject_reason_summary:
        for reason, count in reject_reason_summary.items():
            print(f"  {reason}={count}")
    else:
        print("  NONE")
    print("")

    if not diversified_results:
        print("無合格 candidate（全部未通過 gate）")

        closest_results = sorted(
            raw_results,
            key=lambda item: float(item["rank_score"]),
            reverse=True,
        )[:5]

        print("")
        print("closest_candidates:")
        for idx, item in enumerate(closest_results, start=1):
            metrics = dict(item["metrics"])
            params = dict(item["params"])

            print(f"----- CLOSEST {idx} -----")
            print(f"candidate_no={item['candidate_no']}")
            print(f"rank_score={float(item['rank_score']):.8f}")
            print(f"reject_reason={item.get('reject_reason')}")
            print(f"net_pnl={float(metrics.get('net_pnl', 0.0)):.8f}")
            print(f"profit_factor={float(metrics.get('profit_factor', 0.0)):.8f}")
            print(f"max_drawdown={float(metrics.get('max_drawdown', 0.0)):.8f}")
            print(f"total_trades={int(metrics.get('total_trades', 0))}")
            print(f"win_rate={float(metrics.get('win_rate', 0.0)):.4f}")
            print(f"mutation_tag={params.get('mutation_tag')}")
            print(f"family_tag={_extract_family_tag(params)}")
            _print_weight_summary(params)
            _print_feature_diagnostics(metrics)
            print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
            print("")

        return

    top_n = min(args.top, len(diversified_results))
    for i in range(top_n):
        item = diversified_results[i]
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
        print(f"family_tag={_extract_family_tag(params)}")
        _print_weight_summary(params)
        print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
        print("")


if __name__ == "__main__":
    main()