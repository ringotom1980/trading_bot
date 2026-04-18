"""
Path: governor/analyzer.py
說明：彙整 candidate / walk-forward / diagnostics / search space summary 的分析入口。
"""

from __future__ import annotations

from typing import Any

from storage.repositories.family_performance_summary_repo import (
    get_all_family_performance_summaries,
)
from storage.repositories.feature_diagnostics_summary_repo import (
    get_recent_feature_diagnostics_summaries,
)
from storage.repositories.strategy_candidates_repo import (
    get_latest_run_strategy_candidates,
)


def _build_search_space_summary(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        return {
            "status": "NO_CANDIDATES",
            "candidate_count": 0,
            "negative_net_pnl_count": 0,
        }

    negative_count = 0
    for row in candidates:
        metrics_json = dict(row.get("metrics_json") or row.get("metrics") or {})
        net_pnl = float(metrics_json.get("net_pnl", 0.0))
        if net_pnl <= 0:
            negative_count += 1

    if negative_count == len(candidates):
        return {
            "status": "ALL_FAILED_NET_PNL_NOT_POSITIVE",
            "candidate_count": len(candidates),
            "negative_net_pnl_count": negative_count,
        }

    return {
        "status": "MIXED_RESULTS",
        "candidate_count": len(candidates),
        "negative_net_pnl_count": negative_count,
    }


def analyze_governor_inputs(
    conn,
    *,
    symbol: str,
    interval: str,
) -> dict[str, Any]:
    family_rows = get_all_family_performance_summaries(
        conn,
        symbol=symbol,
        interval=interval,
    )
    feature_rows = get_recent_feature_diagnostics_summaries(
        conn,
        symbol=symbol,
        interval=interval,
        limit=200,
    )
    candidate_rows = get_latest_run_strategy_candidates(
        conn,
        symbol=symbol,
        interval=interval,
    )

    return {
        "symbol": symbol,
        "interval": interval,
        "families": family_rows,
        "features": feature_rows,
        "search_space_summary": _build_search_space_summary(candidate_rows),
    }