"""
Path: scripts/run_walk_forward_validation.py
說明：對指定 candidate 或 top candidates 執行 walk-forward validation，並可寫入 DB。
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

from evolver.promoter import calculate_walk_forward_score
from evolver.walk_forward import run_walk_forward_for_candidate
from storage.db import connection_scope
from storage.repositories.candidate_walk_forward_repo import (
    create_candidate_walk_forward_run,
    insert_candidate_walk_forward_windows,
)
from storage.repositories.strategy_candidates_repo import (
    get_strategy_candidate_by_id,
    get_top_strategy_candidates,
)
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _build_walk_forward_fingerprint(summary: dict[str, object]) -> str:
    payload = {
        "final_status": str(summary.get("final_status") or ""),
        "pass_windows": int(summary.get("pass_windows", 0) or 0),
        "beat_active_windows": int(summary.get("beat_active_windows", 0) or 0),
        "pass_ratio": round(float(summary.get("pass_ratio", 0.0) or 0.0), 4),
        "avg_net_pnl": round(float(summary.get("avg_net_pnl", 0.0) or 0.0), 4),
        "avg_profit_factor": round(float(summary.get("avg_profit_factor", 0.0) or 0.0), 4),
        "avg_max_drawdown": round(float(summary.get("avg_max_drawdown", 0.0) or 0.0), 4),
        "worst_window_drawdown": round(float(summary.get("worst_window_drawdown", 0.0) or 0.0), 4),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _dedupe_walk_forward_results(results: list[dict]) -> list[dict]:
    best_by_fp: dict[str, dict] = {}

    for row in results:
        summary = dict(row.get("summary") or {})
        fp = _build_walk_forward_fingerprint(summary)
        wf_score = float(calculate_walk_forward_score(summary))
        rank_score = float(row.get("rank_score", 0.0) or 0.0)

        existing = best_by_fp.get(fp)
        if existing is None:
            copied = dict(row)
            copied["_wf_score"] = wf_score
            best_by_fp[fp] = copied
            continue

        existing_wf_score = float(existing.get("_wf_score", 0.0) or 0.0)
        existing_rank_score = float(existing.get("rank_score", 0.0) or 0.0)

        if wf_score > existing_wf_score:
            copied = dict(row)
            copied["_wf_score"] = wf_score
            best_by_fp[fp] = copied
            continue

        if wf_score == existing_wf_score and rank_score > existing_rank_score:
            copied = dict(row)
            copied["_wf_score"] = wf_score
            best_by_fp[fp] = copied

    deduped = list(best_by_fp.values())
    deduped.sort(
        key=lambda item: (
            float(item.get("_wf_score", 0.0) or 0.0),
            float(item.get("rank_score", 0.0) or 0.0),
        ),
        reverse=True,
    )
    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward validation")
    parser.add_argument("--candidate-id", type=int, default=None, help="驗證單一 candidate")
    parser.add_argument("--top-limit", type=int, default=None, help="驗證 top N candidates")
    parser.add_argument("--start-date", type=str, required=True, help="validation start YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="validation end YYYY-MM-DD")
    parser.add_argument("--window-days", type=int, default=3, help="單一 walk-forward window 天數")
    parser.add_argument("--step-days", type=int, default=2, help="window 滑動步長天數")
    parser.add_argument("--version-code", type=str, default=None, help="不帶則使用 ACTIVE")
    parser.add_argument("--persist", action="store_true", help="是否將結果寫入 DB")
    args = parser.parse_args()

    if args.candidate_id is None and args.top_limit is None:
        raise ValueError("至少要帶 --candidate-id 或 --top-limit 其中一個")

    if args.candidate_id is not None and args.top_limit is not None:
        raise ValueError("--candidate-id 與 --top-limit 只能擇一使用")

    if args.window_days <= 0:
        raise ValueError("--window-days 必須大於 0")

    if args.step_days <= 0:
        raise ValueError("--step-days 必須大於 0")

    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    if start_time >= end_time:
        raise ValueError("start-date 必須早於 end-date")

    with connection_scope() as conn:
        if args.version_code:
            active_strategy = get_strategy_version_by_code(conn, args.version_code)
            if active_strategy is None:
                raise RuntimeError(f"找不到策略版本：{args.version_code}")
        else:
            active_strategy = get_active_strategy_version(conn)
            if active_strategy is None:
                raise RuntimeError("找不到 ACTIVE 策略版本")

        candidates: list[dict] = []

        if args.candidate_id is not None:
            candidate = get_strategy_candidate_by_id(conn, candidate_id=args.candidate_id)
            if candidate is None:
                raise RuntimeError(f"找不到 candidate_id={args.candidate_id}")
            candidates = [candidate]
        else:
            candidates = get_top_strategy_candidates(
                conn,
                source_strategy_version_id=int(active_strategy["strategy_version_id"]),
                symbol=str(active_strategy["symbol"]),
                interval=str(active_strategy["interval"]),
                tested_range_start=start_time,
                tested_range_end=end_time,
                limit=int(args.top_limit or 10),
                ignore_range=True,
            )
            if not candidates:
                raise RuntimeError("找不到可驗證的 top candidates")

        results: list[dict] = []

        for candidate in candidates:
            result = run_walk_forward_for_candidate(
                conn=conn,
                candidate=candidate,
                active_strategy=active_strategy,
                validation_start=start_time,
                validation_end=end_time,
                window_days=int(args.window_days),
                step_days=int(args.step_days),
            )
            results.append(result)

            if args.persist:
                run_id = create_candidate_walk_forward_run(
                    conn,
                    candidate_id=int(candidate["candidate_id"]),
                    source_strategy_version_id=int(candidate["source_strategy_version_id"]),
                    symbol=str(candidate["symbol"]),
                    interval=str(candidate["interval"]),
                    train_range_start=candidate.get("tested_range_start"),
                    train_range_end=candidate.get("tested_range_end"),
                    validation_range_start=start_time,
                    validation_range_end=end_time,
                    window_days=int(args.window_days),
                    step_days=int(args.step_days),
                    summary=dict(result["summary"]),
                )
                insert_candidate_walk_forward_windows(
                    conn,
                    run_id=run_id,
                    windows=list(result["windows"]),
                )
                
        raw_result_count = len(results)
        results = _dedupe_walk_forward_results(results)

    print("walk-forward validation 完成")
    print(f"validation_range_start={start_time.isoformat()}")
    print(f"validation_range_end={end_time.isoformat()}")
    print(f"raw_validated_count={raw_result_count}")
    print(f"deduped_validated_count={len(results)}")
    print(f"window_days={int(args.window_days)}")
    print(f"step_days={int(args.step_days)}")
    print("")

    for idx, result in enumerate(results, start=1):
        summary = dict(result["summary"])
        wf_score = calculate_walk_forward_score(summary)

        print(f"===== WALK FORWARD {idx} =====")
        print(f"candidate_id={result['candidate_id']}")
        print(f"candidate_no={result['candidate_no']}")
        print(f"rank_score={float(result['rank_score']):.8f}")
        print(f"total_windows={int(summary.get('total_windows', 0))}")
        print(f"pass_windows={int(summary.get('pass_windows', 0))}")
        print(f"beat_active_windows={int(summary.get('beat_active_windows', 0))}")
        print(f"pass_ratio={float(summary.get('pass_ratio', 0.0)):.4f}")
        print(f"avg_net_pnl={float(summary.get('avg_net_pnl', 0.0)):.8f}")
        print(f"avg_profit_factor={float(summary.get('avg_profit_factor', 0.0)):.8f}")
        print(f"avg_max_drawdown={float(summary.get('avg_max_drawdown', 0.0)):.8f}")
        print(f"worst_window_net_pnl={float(summary.get('worst_window_net_pnl', 0.0)):.8f}")
        print(f"worst_window_drawdown={float(summary.get('worst_window_drawdown', 0.0)):.8f}")
        print(f"final_status={summary.get('final_status')}")
        print(f"wf_score={wf_score:.8f}")
        if summary.get("final_reasons"):
            print("final_reasons=" + json.dumps(summary["final_reasons"], ensure_ascii=False))
        print("summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
        print("")

        for window in result["windows"]:
            candidate_metrics = dict(window["candidate_metrics"])
            active_metrics = dict(window["active_metrics"])

            print(f"  --- WINDOW {int(window['window_no'])} ---")
            print(f"  start={window['window_start'].isoformat()}")
            print(f"  end={window['window_end'].isoformat()}")
            print(f"  passed={bool(window['passed'])}")
            print(f"  beat_active={bool(window['beat_active'])}")
            print(f"  candidate_net_pnl={float(candidate_metrics.get('net_pnl', 0.0)):.8f}")
            print(f"  candidate_profit_factor={float(candidate_metrics.get('profit_factor', 0.0)):.8f}")
            print(f"  candidate_max_drawdown={float(candidate_metrics.get('max_drawdown', 0.0)):.8f}")
            print(f"  active_net_pnl={float(active_metrics.get('net_pnl', 0.0)):.8f}")
            print(f"  active_profit_factor={float(active_metrics.get('profit_factor', 0.0)):.8f}")
            print(f"  active_max_drawdown={float(active_metrics.get('max_drawdown', 0.0)):.8f}")
            if window.get("reasons"):
                print("  reasons=" + json.dumps(window["reasons"], ensure_ascii=False))
            print("")


if __name__ == "__main__":
    main()