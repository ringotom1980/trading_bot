"""
Path: scripts/run_candidate_search_and_save.py
說明：執行 candidate search、做行為去重，並將結果寫入 strategy_candidates。
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
from evolver.scorer import calculate_candidate_score
from storage.db import get_connection, connection_scope
from storage.repositories.historical_klines_repo import get_historical_klines_by_range
from storage.repositories.strategy_candidates_repo import (
    delete_strategy_candidates_for_range,
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


def _build_behavior_fingerprint(metrics: dict[str, Any]) -> str:
    payload = {
        "total_trades": int(metrics.get("total_trades", 0)),
        "net_pnl": round(float(metrics.get("net_pnl", 0.0)), 4),
        "profit_factor": round(float(metrics.get("profit_factor", 0.0)), 4),
        "max_drawdown": round(float(metrics.get("max_drawdown", 0.0)), 4),
        "win_rate": round(float(metrics.get("win_rate", 0.0)), 4),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _dedupe_results_by_behavior(results: list[dict[str, object]]) -> list[dict[str, object]]:
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


def _renumber_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    """
    功能：將 deduped 後的 candidate 重新編號，避免 candidate_no 斷裂。
    """
    renumbered: list[dict[str, object]] = []

    for idx, row in enumerate(results, start=1):
        copied = dict(row)
        copied["candidate_no"] = idx
        renumbered.append(copied)

    return renumbered


def _extract_family_tag(params: dict[str, Any]) -> str:
    """
    功能：從 mutation_tag 萃出 family，用來限制同一家族的候選數量。
    """
    mutation_tag = str(params.get("mutation_tag") or "").strip()
    if not mutation_tag:
        return "base"

    if "+" in mutation_tag:
        parts = [part.strip() for part in mutation_tag.split("+") if part.strip()]
        for part in reversed(parts):
            if ":" not in part:
                return part
        return parts[-1] if parts else "unknown"

    if ":" in mutation_tag:
        field_name = mutation_tag.split(":", 1)[0].strip()
        return f"threshold:{field_name}"

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate search and save v3")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--interval", type=str, default=None)
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--version-code", type=str, default=None)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--max-candidates", type=int, default=100, help="最多跑幾組 candidate，預設 100")
    parser.add_argument("--progress-step", type=int, default=10, help="每幾組印一次進度，預設 10")
    parser.add_argument("--commit-step", type=int, default=20, help="每幾組 commit 一次，預設 20")
    parser.add_argument("--per-family-limit", type=int, default=2, help="同一 family 最多保留幾個 candidate，預設 2")
    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise ValueError("--max-candidates 必須大於 0")

    if args.progress_step <= 0:
        raise ValueError("--progress-step 必須大於 0")

    if args.commit_step <= 0:
        raise ValueError("--commit-step 必須大於 0")
    
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

        rank_score = calculate_candidate_score(metrics)

        raw_results.append(
            {
                "rank_score": rank_score,
                "candidate_no": idx,
                "params": candidate_params,
                "metrics": metrics,
            }
        )

        if idx % args.progress_step == 0 or idx == len(candidates):
            elapsed = _format_elapsed(time.time() - started_at)
            print(
                f"[progress] {idx}/{len(candidates)} "
                f"elapsed={elapsed} "
                f"latest_score={rank_score:.8f} "
                f"latest_net_pnl={float(metrics['net_pnl']):.8f}"
            )

    deduped_results = _dedupe_results_by_behavior(raw_results)
    deduped_results.sort(key=lambda item: float(item["rank_score"]), reverse=True)
    diversified_results = _apply_family_diversity_cap(
        deduped_results,
        per_family_limit=args.per_family_limit,
    )
    diversified_results = _renumber_results(diversified_results)

    conn = get_connection()
    saved_count = 0
    deleted_count = 0
    top_rows: list[dict[str, object]] = []

    try:
        deleted_count = delete_strategy_candidates_for_range(
            conn,
            source_strategy_version_id=int(strategy["strategy_version_id"]),
            symbol=symbol,
            interval=interval,
            tested_range_start=start_time,
            tested_range_end=end_time,
        )

        for save_idx, row in enumerate(diversified_results, start=1):
            upsert_strategy_candidate(
                conn,
                source_strategy_version_id=int(strategy["strategy_version_id"]),
                symbol=symbol,
                interval=interval,
                tested_range_start=start_time,
                tested_range_end=end_time,
                candidate_no=int(row["candidate_no"]),
                params=dict(row["params"]),
                metrics=dict(row["metrics"]),
                rank_score=float(row["rank_score"]),
                 note="candidate search v6 - behavior dedupe + family diversity",
            )
            saved_count += 1

            if save_idx % args.commit_step == 0:
                conn.commit()

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
                "raw_candidate_count": len(raw_results),
                "deduped_candidate_count": len(deduped_results),
                "diversified_candidate_count": len(diversified_results),
                "per_family_limit": args.per_family_limit,
                "deleted_count": deleted_count,
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
    print("candidate search and save v3 完成")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"version_code={strategy['version_code']}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"kline_count={len(klines)}")
    print(f"raw_candidate_count={len(raw_results)}")
    print(f"deduped_candidate_count={len(deduped_results)}")
    print(f"diversified_candidate_count={len(diversified_results)}")
    print(f"per_family_limit={args.per_family_limit}")
    print(f"deleted_count={deleted_count}")
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
        print(f"family_tag={_extract_family_tag(params)}")
        _print_weight_summary(params)
        print("params=" + json.dumps(params, ensure_ascii=False, sort_keys=True))
        print("")


if __name__ == "__main__":
    main()