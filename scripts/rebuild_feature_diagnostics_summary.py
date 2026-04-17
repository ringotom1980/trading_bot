"""
Path: scripts/rebuild_feature_diagnostics_summary.py
說明：依 strategy_candidates + candidate_walk_forward_runs 重建 feature_diagnostics_summary。
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
from storage.repositories.feature_diagnostics_summary_repo import (
    upsert_feature_diagnostics_summary,
)
from storage.repositories.strategy_candidates_repo import (
    get_recent_strategy_candidates,
)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _extract_numeric_features(candidate: dict) -> dict[str, float]:
    result: dict[str, float] = {}

    params_json = candidate.get("params_json") or {}
    metrics_json = candidate.get("metrics_json") or {}

    if isinstance(params_json, dict):
        weights = params_json.get("weights")
        if isinstance(weights, dict):
            for side_key in ("long", "short"):
                side_weights = weights.get(side_key)
                if isinstance(side_weights, dict):
                    for feature_key, value in side_weights.items():
                        if _is_number(value):
                            result[f"weight_{side_key}_{feature_key}"] = float(value)

        for key, value in params_json.items():
            if key == "weights":
                continue
            if _is_number(value):
                result[f"param_{key}"] = float(value)

    if isinstance(metrics_json, dict):
        for key, value in metrics_json.items():
            if _is_number(value):
                result[f"metric_{key}"] = float(value)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild feature diagnostics summary")
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

        grouped: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {
                "winner_sum": 0.0,
                "loser_sum": 0.0,
                "winner_count": 0,
                "loser_count": 0,
            }
        )

        used_candidate_count = 0

        for candidate in candidates:
            candidate_id = int(candidate["candidate_id"])
            wf_run = latest_wf_map.get(candidate_id)
            if wf_run is None:
                continue

            used_candidate_count += 1
            is_winner = str(wf_run.get("final_status")) == "PASS"
            numeric_features = _extract_numeric_features(candidate)

            for feature_key, feature_value in numeric_features.items():
                bucket = grouped[feature_key]
                if is_winner:
                    bucket["winner_sum"] += float(feature_value)
                    bucket["winner_count"] += 1
                else:
                    bucket["loser_sum"] += float(feature_value)
                    bucket["loser_count"] += 1

        result_rows: list[dict] = []

        for feature_key, bucket in grouped.items():
            winner_count = int(bucket["winner_count"])
            loser_count = int(bucket["loser_count"])

            winner_avg = float(bucket["winner_sum"]) / winner_count if winner_count > 0 else 0.0
            loser_avg = float(bucket["loser_sum"]) / loser_count if loser_count > 0 else 0.0
            diagnostic_score = winner_avg - loser_avg

            summary_id = upsert_feature_diagnostics_summary(
                conn,
                feature_key=feature_key,
                symbol=args.symbol,
                interval=args.interval,
                winner_avg=winner_avg,
                loser_avg=loser_avg,
                winner_count=winner_count,
                loser_count=loser_count,
                diagnostic_score=diagnostic_score,
            )

            result_rows.append(
                {
                    "summary_id": summary_id,
                    "feature_key": feature_key,
                    "winner_count": winner_count,
                    "loser_count": loser_count,
                    "diagnostic_score": diagnostic_score,
                }
            )

    print(
        json.dumps(
            {
                "symbol": args.symbol,
                "interval": args.interval,
                "candidate_count": len(candidates),
                "used_candidate_count": used_candidate_count,
                "feature_count": len(result_rows),
                "rows": sorted(
                    result_rows,
                    key=lambda x: (x["diagnostic_score"], x["feature_key"]),
                    reverse=True,
                )[:20],
                "rebuilt_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()