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
    }


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
        else:
            decision_id = create_governor_decision(
                conn,
                run_key=run_key,
                decision_type="SEARCH_SPACE_ADJUST",
                target_type="SEARCH_SPACE",
                target_key=scope_key,
                action="KEEP",
                before_value=active_config["config_json"],
                after_value=active_config["config_json"],
                reason={
                    "type": "NO_CHANGE",
                    "message": "active search_space_config exists, keep current config",
                    "active_config_id": active_config["config_id"],
                    "active_config_version": active_config["config_version"],
                },
            )

            decisions.append(
                {
                    "decision_id": decision_id,
                    "action": "KEEP",
                    "target_key": scope_key,
                    "config_id": active_config["config_id"],
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