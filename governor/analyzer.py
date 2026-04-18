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
from storage.repositories.system_events_repo import (
    get_latest_candidate_search_failure_event,
)


def _build_search_space_summary_from_failure_event(
    failure_event: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if failure_event is None:
        return None

    details = dict(failure_event.get("details_json") or {})
    reject_reason_summary = dict(details.get("reject_reason_summary") or {})
    closest_candidates = list(details.get("closest_candidates") or [])

    raw_candidate_count = int(details.get("raw_candidate_count", 0))
    qualified_candidate_count = int(details.get("qualified_candidate_count", 0))

    if raw_candidate_count <= 0:
        return {
            "status": "NO_CANDIDATES",
            "candidate_count": 0,
            "negative_net_pnl_count": 0,
            "source": "failure_event",
            "closest_candidates": [],
        }

    negative_net_pnl_count = int(reject_reason_summary.get("NET_PNL_NOT_POSITIVE", 0))

    if qualified_candidate_count == 0 and negative_net_pnl_count == raw_candidate_count:
        return {
            "status": "ALL_FAILED_NET_PNL_NOT_POSITIVE",
            "candidate_count": raw_candidate_count,
            "negative_net_pnl_count": negative_net_pnl_count,
            "source": "failure_event",
            "event_id": failure_event.get("event_id"),
            "reject_reason_summary": reject_reason_summary,
            "closest_candidates": closest_candidates,
        }

    return {
        "status": "MIXED_RESULTS",
        "candidate_count": raw_candidate_count,
        "negative_net_pnl_count": negative_net_pnl_count,
        "source": "failure_event",
        "event_id": failure_event.get("event_id"),
        "reject_reason_summary": reject_reason_summary,
        "closest_candidates": closest_candidates,
    }


def _build_search_space_summary(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        return {
            "status": "NO_CANDIDATES",
            "candidate_count": 0,
            "negative_net_pnl_count": 0,
            "closest_candidates": [],
        }

    negative_count = 0
    closest_candidates: list[dict[str, Any]] = []

    sorted_candidates = sorted(
        candidates,
        key=lambda row: float(row.get("rank_score", -999999.0)),
        reverse=True,
    )

    for row in candidates:
        metrics_json = dict(row.get("metrics_json") or row.get("metrics") or {})
        net_pnl = float(metrics_json.get("net_pnl", 0.0))
        if net_pnl <= 0:
            negative_count += 1

    for row in sorted_candidates[:5]:
        metrics_json = dict(row.get("metrics_json") or row.get("metrics") or {})
        params_json = dict(row.get("params_json") or row.get("params") or {})
        closest_candidates.append(
            {
                "candidate_id": row.get("candidate_id"),
                "candidate_no": row.get("candidate_no"),
                "rank_score": float(row.get("rank_score", -999999.0)),
                "seed_tag": params_json.get("seed_tag"),
                "mutation_tag": params_json.get("mutation_tag"),
                "reject_reason": row.get("reject_reason"),
                "net_pnl": float(metrics_json.get("net_pnl", 0.0)),
                "profit_factor": float(metrics_json.get("profit_factor", 0.0)),
                "total_trades": int(metrics_json.get("total_trades", 0)),
            }
        )

    if negative_count == len(candidates):
        return {
            "status": "ALL_FAILED_NET_PNL_NOT_POSITIVE",
            "candidate_count": len(candidates),
            "negative_net_pnl_count": negative_count,
            "closest_candidates": closest_candidates,
        }

    return {
        "status": "MIXED_RESULTS",
        "candidate_count": len(candidates),
        "negative_net_pnl_count": negative_count,
        "closest_candidates": closest_candidates,
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
    failure_event = get_latest_candidate_search_failure_event(
        conn,
        symbol=symbol,
        interval=interval,
    )
    failure_summary = _build_search_space_summary_from_failure_event(failure_event)

    if failure_summary is not None:
        search_space_summary = failure_summary
    else:
        candidate_rows = get_latest_run_strategy_candidates(
            conn,
            symbol=symbol,
            interval=interval,
        )
        search_space_summary = _build_search_space_summary(candidate_rows)

    return {
        "symbol": symbol,
        "interval": interval,
        "families": family_rows,
        "features": feature_rows,
        "search_space_summary": search_space_summary,
    }