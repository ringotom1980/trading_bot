"""
Path: governor/governor.py
說明：governor 主入口。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from storage.db import connection_scope
from storage.repositories.governor_decisions_repo import create_governor_decision
from storage.repositories.search_space_config_repo import (
    get_active_search_space_config,
    replace_active_search_space_config,
)

from governor.analyzer import analyze_governor_inputs
from governor.family_manager import build_family_actions
from governor.feature_diagnostics import build_feature_actions
from governor.search_space import build_next_search_space


def _build_scope_key(*, symbol: str, interval: str) -> str:
    return f"{symbol}:{interval}"


def _build_default_search_space() -> dict[str, Any]:
    return {
        "threshold_field_specs": {
            "entry_threshold": [[-0.18, -0.12, -0.08, -0.05, 0.03, 0.05, 0.08, 0.12], 4],
            "exit_threshold": [[-0.12, -0.08, -0.05, 0.05, 0.08, 0.12], 4],
            "reverse_threshold": [[-0.12, -0.08, -0.05, 0.05, 0.08, 0.12], 4],
            "reverse_gap": [[-0.05, -0.03, -0.02, 0.02, 0.03, 0.05], 4],
            "hard_stop_loss_pct": [[-0.010, -0.008, -0.005, 0.005, 0.008, 0.012], 4],
            "take_profit_pct": [[-0.020, -0.015, -0.010, 0.010, 0.015, 0.020], 4],
        },
        "int_field_specs": {
            "cooldown_bars": [-2, -1, 1, 2, 4],
            "min_hold_bars": [-2, -1, 1, 2, 4, 6],
            "max_bars_hold": [-24, -18, -12, 12, 18, 24, 36],
        },
        "base_search_seeds": [],
        "families": {},
        "feature_bias": {},
    }


def _has_any_meaningful_change(
    *,
    current_config: dict[str, Any],
    next_config: dict[str, Any],
) -> bool:
    return current_config != next_config


def _build_search_space_actions(
    *,
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    search_space_actions: list[dict[str, Any]] = []

    summary = dict(analysis.get("search_space_summary") or {})
    status = str(summary.get("status") or "")
    candidate_count = int(summary.get("candidate_count", 0))
    negative_count = int(summary.get("negative_net_pnl_count", 0))
    reject_reason_summary = dict(summary.get("reject_reason_summary") or {})

    if candidate_count <= 0:
        search_space_actions.append(
            {
                "action": "KEEP",
                "reason": {
                    "type": "NO_CANDIDATES",
                    "message": "目前無可用 candidate summary，維持現況",
                    "summary": summary,
                },
            }
        )
        return search_space_actions

    negative_ratio = negative_count / candidate_count
    low_trade_count = int(reject_reason_summary.get("TOTAL_TRADES_TOO_LOW", 0))
    low_trade_ratio = low_trade_count / candidate_count

    if status == "ALL_FAILED_NET_PNL_NOT_POSITIVE":
        search_space_actions.append(
            {
                "action": "TIGHTEN",
                "reason": {
                    "type": "ALL_FAILED_NET_PNL_NOT_POSITIVE",
                    "message": "最近候選全數 net_pnl <= 0，下一輪往更保守、更少交易方向收斂",
                    "summary": summary,
                },
            }
        )
        return search_space_actions

    if negative_ratio >= 0.80 and low_trade_ratio <= 0.25:
        search_space_actions.append(
            {
                "action": "TIGHTEN_SOFT",
                "reason": {
                    "type": "MOSTLY_NEGATIVE_NET_PNL",
                    "message": "大多數候選仍為負報酬，且交易過少比例不高，先做溫和收緊",
                    "summary": summary,
                    "negative_ratio": negative_ratio,
                    "low_trade_ratio": low_trade_ratio,
                },
            }
        )
        return search_space_actions

    if low_trade_ratio >= 0.40:
        search_space_actions.append(
            {
                "action": "LOOSEN",
                "reason": {
                    "type": "TOO_MANY_LOW_TRADE_CANDIDATES",
                    "message": "交易過少比例偏高，下一輪略放鬆 entry 條件",
                    "summary": summary,
                    "negative_ratio": negative_ratio,
                    "low_trade_ratio": low_trade_ratio,
                },
            }
        )
        return search_space_actions

    search_space_actions.append(
        {
            "action": "KEEP",
            "reason": {
                "type": "NO_SEARCH_SPACE_CHANGE",
                "message": "目前沒有觸發 search space 調整條件",
                "summary": summary,
                "negative_ratio": negative_ratio,
                "low_trade_ratio": low_trade_ratio,
            },
        }
    )
    return search_space_actions


def run_governor_cycle(*, run_key: str, symbol: str, interval: str) -> dict[str, Any]:
    scope_key = _build_scope_key(symbol=symbol, interval=interval)
    decisions: list[dict[str, Any]] = []

    with connection_scope() as conn:
        active_config = get_active_search_space_config(conn, scope_key=scope_key)

        if active_config is None:
            default_config = _build_default_search_space()
            config_id = replace_active_search_space_config(
                conn,
                scope_key=scope_key,
                config=default_config,
                created_by="governor_bootstrap",
            )

            decision_id = create_governor_decision(
                conn,
                run_key=run_key,
                decision_type="SEARCH_SPACE_ADJUST",
                target_type="SEARCH_SPACE",
                target_key=scope_key,
                action="REPLACE",
                before_value=None,
                after_value=default_config,
                reason={
                    "type": "BOOTSTRAP",
                    "message": "active search_space_config not found, bootstrap default config",
                },
            )

            decisions.append(
                {
                    "decision_id": decision_id,
                    "action": "REPLACE",
                    "target_key": scope_key,
                    "config_id": config_id,
                }
            )
            current_config = default_config
            active_config_id = config_id
        else:
            current_config = dict(active_config["config_json"] or {})
            active_config_id = active_config["config_id"]

        analysis = analyze_governor_inputs(
            conn,
            symbol=symbol,
            interval=interval,
        )
        family_actions = build_family_actions(analysis["families"])
        feature_actions = build_feature_actions(analysis["features"])
        search_space_actions = _build_search_space_actions(analysis=analysis)

        next_config = build_next_search_space(
            current_config,
            family_actions=family_actions,
            feature_actions=feature_actions,
            search_space_actions=search_space_actions,
        )

        if _has_any_meaningful_change(
            current_config=current_config,
            next_config=next_config,
        ):
            config_id = replace_active_search_space_config(
                conn,
                scope_key=scope_key,
                config=next_config,
                created_by="governor_family_feature_searchspace_adjust",
            )

            decision_id = create_governor_decision(
                conn,
                run_key=run_key,
                decision_type="SEARCH_SPACE_ADJUST",
                target_type="SEARCH_SPACE",
                target_key=scope_key,
                action="REPLACE",
                before_value=current_config,
                after_value=next_config,
                reason={
                    "type": "FAMILY_FEATURE_SEARCHSPACE_ACTIONS_APPLIED",
                    "message": "依 family / feature / search space summary 調整 search space",
                    "family_actions": family_actions,
                    "feature_actions": feature_actions,
                    "search_space_actions": search_space_actions,
                },
            )

            decisions.append(
                {
                    "decision_id": decision_id,
                    "action": "REPLACE",
                    "target_key": scope_key,
                    "config_id": config_id,
                    "family_actions": family_actions,
                    "feature_actions": feature_actions,
                    "search_space_actions": search_space_actions,
                }
            )
        else:
            decision_id = create_governor_decision(
                conn,
                run_key=run_key,
                decision_type="SEARCH_SPACE_ADJUST",
                target_type="SEARCH_SPACE",
                target_key=scope_key,
                action="KEEP",
                before_value=current_config,
                after_value=current_config,
                reason={
                    "type": "NO_CHANGE",
                    "message": "family / feature / search space actions 未造成 search space 變化，維持現況",
                    "family_actions": family_actions,
                    "feature_actions": feature_actions,
                    "search_space_actions": search_space_actions,
                },
            )

            decisions.append(
                {
                    "decision_id": decision_id,
                    "action": "KEEP",
                    "target_key": scope_key,
                    "config_id": active_config_id,
                    "family_actions": family_actions,
                    "feature_actions": feature_actions,
                    "search_space_actions": search_space_actions,
                }
            )

    return {
        "run_key": run_key,
        "symbol": symbol,
        "interval": interval,
        "scope_key": scope_key,
        "status": "COMPLETED",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "decisions": decisions,
    }