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
        "entry_threshold": {"min": 0.5, "max": 0.7},
        "exit_threshold": {"min": 0.3, "max": 0.5},
        "reverse_threshold": {"min": 0.65, "max": 0.8},
        "families": {
            "trend_following_v1": 0.5,
            "mean_reversion_v1": 0.5,
        },
        "feature_bias": {},
    }


def _has_any_meaningful_change(
    *,
    current_config: dict[str, Any],
    next_config: dict[str, Any],
) -> bool:
    return current_config != next_config


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

        next_config = build_next_search_space(
            current_config,
            family_actions=family_actions,
            feature_actions=feature_actions,
        )

        if _has_any_meaningful_change(
            current_config=current_config,
            next_config=next_config,
        ):
            config_id = replace_active_search_space_config(
                conn,
                scope_key=scope_key,
                config=next_config,
                created_by="governor_family_feature_adjust",
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
                    "type": "FAMILY_AND_FEATURE_ACTIONS_APPLIED",
                    "message": "依 family summary 與 feature diagnostics 調整 search space",
                    "family_actions": family_actions,
                    "feature_actions": feature_actions,
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
                    "message": "family / feature actions 未造成 search space 變化，維持現況",
                    "family_actions": family_actions,
                    "feature_actions": feature_actions,
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