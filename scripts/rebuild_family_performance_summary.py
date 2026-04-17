"""
Path: scripts/rebuild_family_performance_summary.py
說明：依 strategy_candidates + candidate_walk_forward_runs 重建 family_performance_summary。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope
from storage.repositories.candidate_walk_forward_repo import (
    get_latest_candidate_walk_forward_runs_map,
)
from storage.repositories.family_performance_summary_repo import (
    upsert_family_performance_summary,
)
from storage.repositories.strategy_candidates_repo import (
    get_recent_strategy_candidates,
)


def _detect_family_key(params_json: dict) -> str:
    if not isinstance(params_json, dict):
        return "unknown_family"

    for key in ("family_key", "family", "strategy_family", "candidate_family"):
        value = params_json.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    tags = params_json.get("tags")
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, str) and item.strip():
                return item.strip()

    return "unknown_family"


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild family performance summary")
    parser.add_argument("--symbol", required=True, help="交易標的，例如 BTCUSDT")
    parser.add_argument("--interval", required=True, help="週期，例如 15m")
    parser.add_argument("--candidate-limit", type=int, default=1000, help="最多讀取幾筆 candidate")
    parser.add_argument("--wf-limit", type=int, default=1000, help="最多讀取幾筆 walk-forward run")
    args = parser.parse_args()

    with connection_scope() as conn:
        candidates = get_recent_strategy_candidates(
            conn,
            symbol=args.symbol,
            interval=args.interval,
            limit=args.candidate_limit,
        )
        latest_wf_map = get_latest_candidate_walk_forward_runs_map(
            conn,
            symbol=args.symbol,
            interval=args.interval,
            limit=args.wf_limit,
        )

        grouped: dict[str, dict] = defaultdict(
            lambda: {
                "sample_count": 0,
                "pass_count": 0,
                "fail_count": 0,
                "rank_score_sum": 0.0,
                "net_pnl_sum": 0.0,
                "profit_factor_sum": 0.0,
                "max_drawdown_sum": 0.0,
                "last_run_at": None,
            }
        )

        used_candidate_count = 0

        for candidate in candidates:
            candidate_id = int(candidate["candidate_id"])
            wf_run = latest_wf_map.get(candidate_id)
            if wf_run is None:
                continue

            used_candidate_count += 1
            family_key = _detect_family_key(candidate.get("params_json") or {})
            bucket = grouped[family_key]

            bucket["sample_count"] += 1
            if str(wf_run.get("final_status")) == "PASS":
                bucket["pass_count"] += 1
            else:
                bucket["fail_count"] += 1

            bucket["rank_score_sum"] += float(candidate.get("rank_score", 0.0))
            bucket["net_pnl_sum"] += float(wf_run.get("avg_net_pnl", 0.0))
            bucket["profit_factor_sum"] += float(wf_run.get("avg_profit_factor", 0.0))
            bucket["max_drawdown_sum"] += float(wf_run.get("avg_max_drawdown", 0.0))

            last_run_at = wf_run.get("created_at")
            if bucket["last_run_at"] is None or (
                last_run_at is not None and last_run_at > bucket["last_run_at"]
            ):
                bucket["last_run_at"] = last_run_at

        result_rows: list[dict] = []

        for family_key, bucket in grouped.items():
            sample_count = int(bucket["sample_count"])
            if sample_count <= 0:
                continue

            summary_id = upsert_family_performance_summary(
                conn,
                family_key=family_key,
                symbol=args.symbol,
                interval=args.interval,
                sample_count=sample_count,
                pass_count=int(bucket["pass_count"]),
                fail_count=int(bucket["fail_count"]),
                avg_rank_score=float(bucket["rank_score_sum"]) / sample_count,
                avg_net_pnl=float(bucket["net_pnl_sum"]) / sample_count,
                avg_profit_factor=float(bucket["profit_factor_sum"]) / sample_count,
                avg_max_drawdown=float(bucket["max_drawdown_sum"]) / sample_count,
                last_run_at=bucket["last_run_at"],
            )

            result_rows.append(
                {
                    "summary_id": summary_id,
                    "family_key": family_key,
                    "sample_count": sample_count,
                    "pass_count": int(bucket["pass_count"]),
                    "fail_count": int(bucket["fail_count"]),
                }
            )

    print(
        json.dumps(
            {
                "symbol": args.symbol,
                "interval": args.interval,
                "candidate_count": len(candidates),
                "used_candidate_count": used_candidate_count,
                "family_count": len(result_rows),
                "rows": result_rows,
                "rebuilt_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()