"""
Path: governor/search_space.py
說明：search space 讀寫與調整。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _ensure_default_search_space_structure(config: dict[str, Any] | None) -> dict[str, Any]:
    next_config = deepcopy(config or {})

    next_config.setdefault("threshold_field_specs", {})
    next_config.setdefault("int_field_specs", {})
    next_config.setdefault("base_search_seeds", [])
    next_config.setdefault("families", {})
    next_config.setdefault("feature_bias", {})

    return next_config


def _get_seed_overrides(seed: dict[str, Any]) -> dict[str, Any]:
    overrides = seed.get("overrides")
    if isinstance(overrides, dict):
        return overrides
    seed["overrides"] = {}
    return seed["overrides"]


def _tighten_seed_overrides(seed: dict[str, Any]) -> None:
    overrides = _get_seed_overrides(seed)

    if "entry_threshold" in overrides:
        overrides["entry_threshold"] = min(0.90, round(float(overrides["entry_threshold"]) + 0.02, 6))

    if "entry_min_gap" in overrides:
        overrides["entry_min_gap"] = min(0.40, round(float(overrides["entry_min_gap"]) + 0.01, 6))

    if "entry_confirm_score" in overrides:
        overrides["entry_confirm_score"] = min(0.95, round(float(overrides["entry_confirm_score"]) + 0.02, 6))

    if "cooldown_bars" in overrides:
        overrides["cooldown_bars"] = min(12, int(overrides["cooldown_bars"]) + 1)

    if "min_hold_bars" in overrides:
        overrides["min_hold_bars"] = min(48, int(overrides["min_hold_bars"]) + 1)

    if "max_bars_hold" in overrides:
        overrides["max_bars_hold"] = min(240, int(overrides["max_bars_hold"]) + 4)


def _soft_tighten_seed_overrides(seed: dict[str, Any]) -> None:
    overrides = _get_seed_overrides(seed)

    if "entry_threshold" in overrides:
        overrides["entry_threshold"] = min(0.90, round(float(overrides["entry_threshold"]) + 0.01, 6))

    if "entry_min_gap" in overrides:
        overrides["entry_min_gap"] = min(0.40, round(float(overrides["entry_min_gap"]) + 0.005, 6))

    if "entry_confirm_score" in overrides:
        overrides["entry_confirm_score"] = min(0.95, round(float(overrides["entry_confirm_score"]) + 0.01, 6))

    if "cooldown_bars" in overrides:
        overrides["cooldown_bars"] = min(12, int(overrides["cooldown_bars"]) + 1)

    if "min_hold_bars" in overrides:
        overrides["min_hold_bars"] = min(48, int(overrides["min_hold_bars"]) + 1)

    if "max_bars_hold" in overrides:
        overrides["max_bars_hold"] = min(240, int(overrides["max_bars_hold"]) + 2)


def _loosen_seed_overrides(seed: dict[str, Any]) -> None:
    overrides = _get_seed_overrides(seed)

    if "entry_threshold" in overrides:
        overrides["entry_threshold"] = max(0.30, round(float(overrides["entry_threshold"]) - 0.01, 6))

    if "entry_min_gap" in overrides:
        overrides["entry_min_gap"] = max(0.02, round(float(overrides["entry_min_gap"]) - 0.005, 6))

    if "entry_confirm_score" in overrides:
        overrides["entry_confirm_score"] = max(0.30, round(float(overrides["entry_confirm_score"]) - 0.01, 6))

    if "cooldown_bars" in overrides:
        overrides["cooldown_bars"] = max(0, int(overrides["cooldown_bars"]) - 1)

    if "min_hold_bars" in overrides:
        overrides["min_hold_bars"] = max(1, int(overrides["min_hold_bars"]) - 1)

    if "max_bars_hold" in overrides:
        overrides["max_bars_hold"] = max(4, int(overrides["max_bars_hold"]) - 2)


def _tighten_threshold_field_specs(threshold_specs: dict[str, Any]) -> None:
    for field in ("entry_threshold",):
        spec = threshold_specs.get(field)
        if not isinstance(spec, list) or len(spec) != 2:
            continue

        deltas, digits = spec
        if not isinstance(deltas, list):
            continue

        tightened = [delta for delta in deltas if float(delta) >= -0.08]
        if tightened:
            threshold_specs[field] = [tightened, digits]


def _tighten_int_field_specs(int_specs: dict[str, Any]) -> None:
    cooldown = int_specs.get("cooldown_bars")
    if isinstance(cooldown, list):
        int_specs["cooldown_bars"] = [delta for delta in cooldown if int(delta) >= -1]

    min_hold = int_specs.get("min_hold_bars")
    if isinstance(min_hold, list):
        int_specs["min_hold_bars"] = [delta for delta in min_hold if int(delta) >= -1]


def _apply_governor_policy(
    next_config: dict[str, Any],
    *,
    search_space_actions: list[dict[str, Any]] | None = None,
) -> None:
    for action in search_space_actions or []:
        action_type = str(action.get("action") or "KEEP")

        threshold_specs = next_config.get("threshold_field_specs")
        int_specs = next_config.get("int_field_specs")
        base_search_seeds = next_config.get("base_search_seeds")

        if action_type == "TIGHTEN":
            if isinstance(threshold_specs, dict):
                _tighten_threshold_field_specs(threshold_specs)
            if isinstance(int_specs, dict):
                _tighten_int_field_specs(int_specs)
            if isinstance(base_search_seeds, list):
                for seed in base_search_seeds:
                    if isinstance(seed, dict):
                        _tighten_seed_overrides(seed)

        elif action_type == "TIGHTEN_SOFT":
            if isinstance(base_search_seeds, list):
                for seed in base_search_seeds:
                    if isinstance(seed, dict):
                        _soft_tighten_seed_overrides(seed)

        elif action_type == "LOOSEN":
            if isinstance(base_search_seeds, list):
                for seed in base_search_seeds:
                    if isinstance(seed, dict):
                        _loosen_seed_overrides(seed)


def build_next_search_space(
    current_config: dict[str, Any] | None,
    *,
    family_actions: list[dict[str, Any]] | None = None,
    feature_actions: list[dict[str, Any]] | None = None,
    search_space_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    next_config = _ensure_default_search_space_structure(current_config)

    families = dict(next_config.get("families") or {})
    for item in family_actions or []:
        family_key = str(item["family_key"])
        target_weight = float(item["target_weight"])
        families[family_key] = target_weight
    next_config["families"] = families

    feature_bias = dict(next_config.get("feature_bias") or {})
    for item in feature_actions or []:
        feature_key = str(item["feature_key"])
        target_bias = float(item["target_bias"])
        feature_bias[feature_key] = target_bias
    next_config["feature_bias"] = feature_bias

    _apply_governor_policy(
        next_config,
        search_space_actions=search_space_actions,
    )

    return next_config