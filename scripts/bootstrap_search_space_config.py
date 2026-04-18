"""
Path: scripts/bootstrap_search_space_config.py
說明：為指定 scope 建立第一筆 active search_space_config。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.db import connection_scope
from storage.repositories.search_space_config_repo import (
    get_active_search_space_config,
    replace_active_search_space_config,
)


DEFAULT_SEARCH_SPACE_CONFIG: dict = {
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
    "base_search_seeds": [
        {
            "name": "seed_base_current",
            "overrides": {
                "entry_threshold": 0.60,
                "entry_min_gap": 0.14,
                "entry_confirm_score": 0.66,
                "exit_threshold": 0.36,
                "reverse_threshold": 0.68,
                "reverse_gap": 0.10,
                "hard_stop_loss_pct": 0.015,
                "take_profit_pct": 0.03,
                "cooldown_bars": 4,
                "min_hold_bars": 2,
                "max_bars_hold": 24,
            },
            "weight_template": None,
        },
        {
            "name": "seed_trend_balanced",
            "overrides": {
                "entry_threshold": 0.64,
                "entry_min_gap": 0.16,
                "entry_confirm_score": 0.70,
                "exit_threshold": 0.40,
                "reverse_threshold": 0.74,
                "reverse_gap": 0.12,
                "hard_stop_loss_pct": 0.015,
                "take_profit_pct": 0.03,
                "cooldown_bars": 5,
                "min_hold_bars": 3,
                "max_bars_hold": 28,
            },
            "weight_template": "trend_up",
        },
        {
            "name": "seed_momentum_balanced",
            "overrides": {
                "entry_threshold": 0.62,
                "entry_min_gap": 0.15,
                "entry_confirm_score": 0.68,
                "exit_threshold": 0.38,
                "reverse_threshold": 0.72,
                "reverse_gap": 0.11,
                "hard_stop_loss_pct": 0.015,
                "take_profit_pct": 0.03,
                "cooldown_bars": 4,
                "min_hold_bars": 2,
                "max_bars_hold": 22,
            },
            "weight_template": "momentum_up",
        },
        {
            "name": "seed_volume_combo",
            "overrides": {
                "entry_threshold": 0.60,
                "entry_min_gap": 0.15,
                "entry_confirm_score": 0.68,
                "exit_threshold": 0.37,
                "reverse_threshold": 0.70,
                "reverse_gap": 0.10,
                "hard_stop_loss_pct": 0.014,
                "take_profit_pct": 0.025,
                "cooldown_bars": 4,
                "min_hold_bars": 2,
                "max_bars_hold": 20,
            },
            "weight_template": "volume_momentum_combo",
        },
        {
            "name": "seed_conservative",
            "overrides": {
                "entry_threshold": 0.68,
                "entry_min_gap": 0.18,
                "entry_confirm_score": 0.72,
                "exit_threshold": 0.44,
                "reverse_threshold": 0.78,
                "reverse_gap": 0.14,
                "hard_stop_loss_pct": 0.012,
                "take_profit_pct": 0.025,
                "cooldown_bars": 6,
                "min_hold_bars": 3,
                "max_bars_hold": 28,
            },
            "weight_template": "trend_only",
        },
        {
            "name": "seed_aggressive",
            "overrides": {
                "entry_threshold": 0.58,
                "entry_min_gap": 0.14,
                "entry_confirm_score": 0.66,
                "exit_threshold": 0.36,
                "reverse_threshold": 0.68,
                "reverse_gap": 0.10,
                "hard_stop_loss_pct": 0.02,
                "take_profit_pct": 0.04,
                "cooldown_bars": 3,
                "min_hold_bars": 2,
                "max_bars_hold": 16,
            },
            "weight_template": "momentum_only",
        },
        {
            "name": "seed_asymmetric_trend_momentum",
            "overrides": {
                "entry_threshold": 0.62,
                "entry_min_gap": 0.16,
                "entry_confirm_score": 0.69,
                "exit_threshold": 0.38,
                "reverse_threshold": 0.72,
                "reverse_gap": 0.11,
                "hard_stop_loss_pct": 0.015,
                "take_profit_pct": 0.03,
                "cooldown_bars": 4,
                "min_hold_bars": 2,
                "max_bars_hold": 24,
            },
            "weight_template": "long_trend_short_momentum",
        },
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap active search space config")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--force-replace", action="store_true")
    args = parser.parse_args()

    scope_key = f"{args.symbol}:{args.interval}"

    with connection_scope() as conn:
        active_row = get_active_search_space_config(conn, scope_key=scope_key)

        if active_row is not None and not args.force_replace:
            print(
                json.dumps(
                    {
                        "scope_key": scope_key,
                        "status": "SKIPPED_ALREADY_EXISTS",
                        "config_id": active_row["config_id"],
                        "config_version": active_row["config_version"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return

        config_id = replace_active_search_space_config(
            conn,
            scope_key=scope_key,
            config=DEFAULT_SEARCH_SPACE_CONFIG,
            created_by="bootstrap_search_space_config",
        )

        active_row = get_active_search_space_config(conn, scope_key=scope_key)

    print(
        json.dumps(
            {
                "scope_key": scope_key,
                "status": "BOOTSTRAPPED",
                "config_id": config_id,
                "config_version": active_row["config_version"] if active_row else None,
                "created_by": "bootstrap_search_space_config",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()