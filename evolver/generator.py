"""
Path: evolver/generator.py
說明：Candidate Generator v8
- 加入真正獨立的 base search seeds
- 不再只圍繞目前 ACTIVE strategy 微調
- 保留 threshold / profile / weights / combo 搜尋
- 保留 fingerprint 去重
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from strategy.signals import DEFAULT_WEIGHTS


THRESHOLD_FIELD_SPECS: dict[str, tuple[list[float], int]] = {
    "entry_threshold": ([-0.18, -0.12, -0.08, -0.05, 0.03, 0.05, 0.08, 0.12], 4),
    "exit_threshold": ([-0.12, -0.08, -0.05, 0.05, 0.08, 0.12], 4),
    "reverse_threshold": ([-0.12, -0.08, -0.05, 0.05, 0.08, 0.12], 4),
    "reverse_gap": ([-0.05, -0.03, -0.02, 0.02, 0.03, 0.05], 4),
    "hard_stop_loss_pct": ([-0.010, -0.008, -0.005, 0.005, 0.008, 0.012], 4),
    "take_profit_pct": ([-0.020, -0.015, -0.010, 0.010, 0.015, 0.020], 4),
}

INT_FIELD_SPECS: dict[str, list[int]] = {
    "cooldown_bars": [-2, -1, 1, 2, 4],
    "min_hold_bars": [-2, -1, 1, 2, 4, 6],
    "max_bars_hold": [-24, -18, -12, 12, 18, 24, 36],
}

WEIGHT_MUTATION_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "trend_up",
        "long": {
            "close_vs_sma20_pct": 0.12,
            "close_vs_sma60_pct": 0.12,
            "slope_5": -0.06,
            "slope_10": -0.06,
            "volume_ratio_20": -0.12,
        },
        "short": {
            "close_vs_sma20_pct": 0.12,
            "close_vs_sma60_pct": 0.12,
            "slope_5": -0.06,
            "slope_10": -0.06,
            "volume_ratio_20": -0.12,
        },
    },
    {
        "name": "momentum_up",
        "long": {
            "close_vs_sma20_pct": -0.06,
            "close_vs_sma60_pct": -0.06,
            "slope_5": 0.12,
            "slope_10": 0.12,
            "volume_ratio_20": -0.12,
        },
        "short": {
            "close_vs_sma20_pct": -0.06,
            "close_vs_sma60_pct": -0.06,
            "slope_5": 0.12,
            "slope_10": 0.12,
            "volume_ratio_20": -0.12,
        },
    },
    {
        "name": "volume_up",
        "long": {
            "close_vs_sma20_pct": -0.05,
            "close_vs_sma60_pct": -0.05,
            "slope_5": -0.05,
            "slope_10": -0.05,
            "volume_ratio_20": 0.20,
        },
        "short": {
            "close_vs_sma20_pct": -0.05,
            "close_vs_sma60_pct": -0.05,
            "slope_5": -0.05,
            "slope_10": -0.05,
            "volume_ratio_20": 0.20,
        },
    },
    {
        "name": "trend_momentum_up",
        "long": {
            "close_vs_sma20_pct": 0.08,
            "close_vs_sma60_pct": 0.08,
            "slope_5": 0.08,
            "slope_10": 0.08,
            "volume_ratio_20": -0.32,
        },
        "short": {
            "close_vs_sma20_pct": 0.08,
            "close_vs_sma60_pct": 0.08,
            "slope_5": 0.08,
            "slope_10": 0.08,
            "volume_ratio_20": -0.32,
        },
    },
    {
        "name": "trend_only",
        "long": {
            "close_vs_sma20_pct": 0.15,
            "close_vs_sma60_pct": 0.15,
            "slope_5": -0.10,
            "slope_10": -0.10,
            "volume_ratio_20": -0.10,
        },
        "short": {
            "close_vs_sma20_pct": 0.15,
            "close_vs_sma60_pct": 0.15,
            "slope_5": -0.10,
            "slope_10": -0.10,
            "volume_ratio_20": -0.10,
        },
    },
    {
        "name": "momentum_only",
        "long": {
            "close_vs_sma20_pct": -0.10,
            "close_vs_sma60_pct": -0.10,
            "slope_5": 0.15,
            "slope_10": 0.15,
            "volume_ratio_20": -0.10,
        },
        "short": {
            "close_vs_sma20_pct": -0.10,
            "close_vs_sma60_pct": -0.10,
            "slope_5": 0.15,
            "slope_10": 0.15,
            "volume_ratio_20": -0.10,
        },
    },
    {
        "name": "long_trend_short_momentum",
        "long": {
            "close_vs_sma20_pct": 0.14,
            "close_vs_sma60_pct": 0.14,
            "slope_5": -0.08,
            "slope_10": -0.08,
            "volume_ratio_20": -0.12,
        },
        "short": {
            "close_vs_sma20_pct": -0.08,
            "close_vs_sma60_pct": -0.08,
            "slope_5": 0.14,
            "slope_10": 0.14,
            "volume_ratio_20": -0.12,
        },
    },
    {
        "name": "long_momentum_short_trend",
        "long": {
            "close_vs_sma20_pct": -0.08,
            "close_vs_sma60_pct": -0.08,
            "slope_5": 0.14,
            "slope_10": 0.14,
            "volume_ratio_20": -0.12,
        },
        "short": {
            "close_vs_sma20_pct": 0.14,
            "close_vs_sma60_pct": 0.14,
            "slope_5": -0.08,
            "slope_10": -0.08,
            "volume_ratio_20": -0.12,
        },
    },
    {
        "name": "long_aggressive_short_defensive",
        "long": {
            "close_vs_sma20_pct": -0.12,
            "close_vs_sma60_pct": -0.12,
            "slope_5": 0.18,
            "slope_10": 0.18,
            "volume_ratio_20": -0.12,
        },
        "short": {
            "close_vs_sma20_pct": 0.08,
            "close_vs_sma60_pct": 0.08,
            "slope_5": -0.04,
            "slope_10": -0.04,
            "volume_ratio_20": -0.08,
        },
    },
    {
        "name": "long_defensive_short_aggressive",
        "long": {
            "close_vs_sma20_pct": 0.08,
            "close_vs_sma60_pct": 0.08,
            "slope_5": -0.04,
            "slope_10": -0.04,
            "volume_ratio_20": -0.08,
        },
        "short": {
            "close_vs_sma20_pct": -0.12,
            "close_vs_sma60_pct": -0.12,
            "slope_5": 0.18,
            "slope_10": 0.18,
            "volume_ratio_20": -0.12,
        },
    },
    {
        "name": "volume_momentum_combo",
        "long": {
            "close_vs_sma20_pct": -0.06,
            "close_vs_sma60_pct": -0.06,
            "slope_5": 0.10,
            "slope_10": 0.10,
            "volume_ratio_20": 0.14,
        },
        "short": {
            "close_vs_sma20_pct": -0.06,
            "close_vs_sma60_pct": -0.06,
            "slope_5": 0.10,
            "slope_10": 0.10,
            "volume_ratio_20": 0.14,
        },
    },
]

PROFILE_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "hold_short",
        "overrides": {
            "min_hold_bars": 1,
            "max_bars_hold": 12,
        },
    },
    {
        "name": "hold_medium",
        "overrides": {
            "min_hold_bars": 2,
            "max_bars_hold": 24,
        },
    },
    {
        "name": "hold_long",
        "overrides": {
            "min_hold_bars": 4,
            "max_bars_hold": 36,
        },
    },
    {
        "name": "risk_tight",
        "overrides": {
            "hard_stop_loss_pct": 0.012,
            "take_profit_pct": 0.025,
        },
    },
    {
        "name": "risk_balanced",
        "overrides": {
            "hard_stop_loss_pct": 0.015,
            "take_profit_pct": 0.03,
        },
    },
    {
        "name": "risk_wide",
        "overrides": {
            "hard_stop_loss_pct": 0.025,
            "take_profit_pct": 0.05,
        },
    },
    {
        "name": "entry_loose",
        "overrides": {
            "entry_threshold": 0.48,
            "reverse_threshold": 0.62,
            "reverse_gap": 0.08,
        },
    },
    {
        "name": "entry_balanced",
        "overrides": {
            "entry_threshold": 0.54,
            "reverse_threshold": 0.66,
            "reverse_gap": 0.10,
        },
    },
    {
        "name": "entry_loose_balanced",
        "overrides": {
            "entry_threshold": 0.50,
            "reverse_threshold": 0.64,
            "reverse_gap": 0.09,
        },
    },
    {
        "name": "entry_strict",
        "overrides": {
            "entry_threshold": 0.68,
            "reverse_threshold": 0.76,
            "reverse_gap": 0.14,
        },
    },
    {
        "name": "fast_exit",
        "overrides": {
            "exit_threshold": 0.48,
            "max_bars_hold": 12,
        },
    },
    {
        "name": "slow_exit",
        "overrides": {
            "exit_threshold": 0.36,
            "max_bars_hold": 30,
        },
    },
    {
        "name": "risk_minimal_tp_off",
        "overrides": {
            "hard_stop_loss_pct": 0.012,
            "take_profit_pct": 0.0,
        },
    },
]

BASE_SEARCH_SEEDS: list[dict[str, Any]] = [
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
]


def _round_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _clamp_float(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def _copy_params(base_params: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(base_params)


def _apply_safe_defaults(params: dict[str, Any]) -> dict[str, Any]:
    normalized = _copy_params(params)

    if float(normalized.get("entry_threshold", 0.0)) <= 0:
        normalized["entry_threshold"] = 0.55

    if float(normalized.get("exit_threshold", 0.0)) <= 0:
        normalized["exit_threshold"] = 0.35

    if float(normalized.get("reverse_threshold", 0.0)) <= 0:
        normalized["reverse_threshold"] = 0.65

    if float(normalized.get("reverse_gap", 0.0)) <= 0:
        normalized["reverse_gap"] = 0.10
        
    if float(normalized.get("entry_min_gap", 0.0)) <= 0:
        normalized["entry_min_gap"] = 0.12

    if float(normalized.get("entry_confirm_score", 0.0)) <= 0:
        normalized["entry_confirm_score"] = 0.64

    if float(normalized.get("hard_stop_loss_pct", 0.0)) <= 0:
        normalized["hard_stop_loss_pct"] = 0.015

    if "take_profit_pct" not in normalized:
        normalized["take_profit_pct"] = 0.0

    if int(normalized.get("cooldown_bars", -1)) < 0:
        normalized["cooldown_bars"] = 1

    if int(normalized.get("min_hold_bars", 0)) <= 0:
        normalized["min_hold_bars"] = 1

    if int(normalized.get("max_bars_hold", 0)) <= int(normalized.get("min_hold_bars", 1)):
        normalized["max_bars_hold"] = max(int(normalized.get("min_hold_bars", 1)) + 12, 24)

    return normalized


def _resolve_base_weights(base_params: dict[str, Any]) -> dict[str, dict[str, float]]:
    base_weights = base_params.get("weights")
    if not isinstance(base_weights, dict):
        return deepcopy(DEFAULT_WEIGHTS)

    long_weights = base_weights.get("long")
    short_weights = base_weights.get("short")

    if not isinstance(long_weights, dict) or not isinstance(short_weights, dict):
        return deepcopy(DEFAULT_WEIGHTS)

    resolved = {"long": {}, "short": {}}

    for side in ("long", "short"):
        source = long_weights if side == "long" else short_weights
        for key, default_value in DEFAULT_WEIGHTS[side].items():
            resolved[side][key] = float(source.get(key, default_value))

    return resolved


def _normalize_weight_map(weight_map: dict[str, float]) -> dict[str, float]:
    cleaned = {key: max(0.000001, float(value)) for key, value in weight_map.items()}
    total = sum(cleaned.values())

    if total <= 0:
        equal_weight = 1.0 / len(cleaned)
        return {key: _round_float(equal_weight, 6) for key in cleaned}

    return {
        key: _round_float(value / total, 6)
        for key, value in cleaned.items()
    }


def _canonicalize_params(params: dict[str, Any]) -> dict[str, Any]:
    canonical = _copy_params(params)
    canonical.pop("mutation_tag", None)

    float_fields = [
        "entry_threshold",
        "entry_min_gap",
        "entry_confirm_score",
        "exit_threshold",
        "reverse_threshold",
        "reverse_gap",
        "hard_stop_loss_pct",
        "take_profit_pct",
        "fee_rate",
        "slippage_rate",
    ]
    int_fields = [
        "cooldown_bars",
        "min_hold_bars",
        "max_bars_hold",
    ]

    for key in float_fields:
        if key in canonical:
            canonical[key] = _round_float(float(canonical[key]), 6)

    for key in int_fields:
        if key in canonical:
            canonical[key] = int(canonical[key])

    weights = canonical.get("weights")
    if isinstance(weights, dict):
        normalized_weights: dict[str, dict[str, float]] = {}
        for side in ("long", "short"):
            side_weights = weights.get(side)
            if isinstance(side_weights, dict):
                normalized_weights[side] = _normalize_weight_map(side_weights)
        canonical["weights"] = normalized_weights

    return canonical


def _build_candidate_fingerprint(params: dict[str, Any]) -> str:
    canonical = _canonicalize_params(params)
    return json.dumps(canonical, ensure_ascii=False, sort_keys=True)


def _find_weight_template_by_name(name: str) -> dict[str, Any] | None:
    for template in WEIGHT_MUTATION_TEMPLATES:
        if str(template.get("name")) == name:
            return template
    return None


def _apply_weight_template(
    *,
    base_weights: dict[str, dict[str, float]],
    template_name: str | None,
) -> dict[str, dict[str, float]]:
    if not template_name:
        return {
            "long": _normalize_weight_map(base_weights["long"]),
            "short": _normalize_weight_map(base_weights["short"]),
        }

    template = _find_weight_template_by_name(template_name)
    if template is None:
        return {
            "long": _normalize_weight_map(base_weights["long"]),
            "short": _normalize_weight_map(base_weights["short"]),
        }

    result: dict[str, dict[str, float]] = {"long": {}, "short": {}}
    for side in ("long", "short"):
        mutated = dict(base_weights[side])
        side_delta = template.get(side, {})
        for key, delta in side_delta.items():
            if key not in mutated:
                continue
            mutated[key] = _clamp_float(mutated[key] + float(delta), 0.000001, 0.95)
        result[side] = _normalize_weight_map(mutated)

    return result


def _build_seed_params(base_params: dict[str, Any]) -> list[dict[str, Any]]:
    normalized_base = _apply_safe_defaults(base_params)
    resolved_base_weights = _resolve_base_weights(normalized_base)

    seeds: list[dict[str, Any]] = []

    for seed in BASE_SEARCH_SEEDS:
        params = _copy_params(normalized_base)

        for key, value in dict(seed.get("overrides") or {}).items():
            params[key] = value

        params["weights"] = _apply_weight_template(
            base_weights=resolved_base_weights,
            template_name=seed.get("weight_template"),
        )
        params["mutation_tag"] = str(seed["name"])
        params["seed_tag"] = str(seed["name"])
        seeds.append(_apply_safe_defaults(params))

    return seeds


def _build_weight_variants(base_params: dict[str, Any]) -> list[dict[str, Any]]:
    base_params = _apply_safe_defaults(base_params)
    base_weights = _resolve_base_weights(base_params)
    variants: list[dict[str, Any]] = []

    base_candidate = _copy_params(base_params)
    base_candidate["weights"] = {
        "long": _normalize_weight_map(base_weights["long"]),
        "short": _normalize_weight_map(base_weights["short"]),
    }
    variants.append(base_candidate)

    for template in WEIGHT_MUTATION_TEMPLATES:
        params = _copy_params(base_params)
        params["mutation_tag"] = template["name"]
        params["weights"] = {"long": {}, "short": {}}

        for side in ("long", "short"):
            mutated = dict(base_weights[side])
            side_delta = template.get(side, {})

            for key, delta in side_delta.items():
                if key not in mutated:
                    continue
                mutated[key] = _clamp_float(mutated[key] + float(delta), 0.000001, 0.95)

            params["weights"][side] = _normalize_weight_map(mutated)

        variants.append(params)

    return variants


def _build_threshold_variants(base_params: dict[str, Any]) -> list[dict[str, Any]]:
    base_params = _apply_safe_defaults(base_params)
    variants: list[dict[str, Any]] = []

    for field, (deltas, digits) in THRESHOLD_FIELD_SPECS.items():
        base_value = float(base_params.get(field, 0.0))
        for delta in deltas:
            params = _copy_params(base_params)
            new_value = _round_float(base_value + delta, digits)

            if field in {"entry_threshold", "exit_threshold", "reverse_threshold"}:
                new_value = _clamp_float(new_value, 0.30, 0.90)
            elif field == "reverse_gap":
                new_value = _clamp_float(new_value, 0.04, 0.25)
            elif field == "hard_stop_loss_pct":
                new_value = _clamp_float(new_value, 0.008, 0.04)
            elif field == "take_profit_pct":
                new_value = _clamp_float(new_value, 0.0, 0.10)

            if _round_float(new_value, 6) == _round_float(base_value, 6):
                continue

            params[field] = new_value
            params["mutation_tag"] = f"{field}:{delta:+}"
            variants.append(params)

    for field, deltas in INT_FIELD_SPECS.items():
        base_value = int(base_params.get(field, 0))
        for delta in deltas:
            params = _copy_params(base_params)

            if field == "cooldown_bars":
                new_value = _clamp_int(base_value + delta, 0, 12)
            elif field == "min_hold_bars":
                new_value = _clamp_int(base_value + delta, 1, 48)
            else:
                new_value = _clamp_int(base_value + delta, 4, 240)

            if new_value == base_value:
                continue

            params[field] = new_value
            params["mutation_tag"] = f"{field}:{delta:+}"
            variants.append(params)

    return variants


def _build_profile_variants(base_params: dict[str, Any]) -> list[dict[str, Any]]:
    base_params = _apply_safe_defaults(base_params)
    variants: list[dict[str, Any]] = []

    for template in PROFILE_TEMPLATES:
        params = _copy_params(base_params)

        for key, value in template.get("overrides", {}).items():
            params[key] = value

        params["mutation_tag"] = template["name"]
        variants.append(_apply_safe_defaults(params))

    return variants


def _is_valid_candidate(params: dict[str, Any]) -> bool:
    entry_threshold = float(params.get("entry_threshold", 0.0))
    exit_threshold = float(params.get("exit_threshold", 0.0))
    reverse_threshold = float(params.get("reverse_threshold", 0.0))
    reverse_gap = float(params.get("reverse_gap", 0.0))
    cooldown_bars = int(params.get("cooldown_bars", 0))
    min_hold_bars = int(params.get("min_hold_bars", 1))
    max_bars_hold = int(params.get("max_bars_hold", 1))
    hard_stop_loss_pct = float(params.get("hard_stop_loss_pct", 0.0))
    take_profit_pct = float(params.get("take_profit_pct", 0.0))

    if exit_threshold >= entry_threshold:
        return False
    if reverse_threshold < entry_threshold:
        return False
    if reverse_gap <= 0:
        return False
    if cooldown_bars < 0:
        return False
    if min_hold_bars >= max_bars_hold:
        return False
    if hard_stop_loss_pct <= 0:
        return False
    if take_profit_pct < 0:
        return False
    if take_profit_pct > 0 and take_profit_pct <= hard_stop_loss_pct:
        return False

    weights = params.get("weights")
    if not isinstance(weights, dict):
        return False

    long_weights = weights.get("long")
    short_weights = weights.get("short")
    if not isinstance(long_weights, dict) or not isinstance(short_weights, dict):
        return False

    for side_weights in (long_weights, short_weights):
        if not side_weights:
            return False
        if sum(float(v) for v in side_weights.values()) <= 0:
            return False

    return True


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for params in candidates:
        fingerprint = _build_candidate_fingerprint(params)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(params)

    return deduped


def _generate_candidates_from_seed(seed_params: dict[str, Any]) -> list[dict[str, Any]]:
    normalized_seed = _apply_safe_defaults(seed_params)
    weight_variants = _build_weight_variants(normalized_seed)
    threshold_variants = _build_threshold_variants(normalized_seed)
    profile_variants = _build_profile_variants(normalized_seed)

    candidates: list[dict[str, Any]] = []
    candidates.append(normalized_seed)

    for params in weight_variants[1:]:
        params["seed_tag"] = normalized_seed.get("seed_tag")
        candidates.append(params)

    for params in threshold_variants:
        if "weights" not in params:
            params["weights"] = deepcopy(normalized_seed["weights"])
        params["seed_tag"] = normalized_seed.get("seed_tag")
        candidates.append(params)

    for params in profile_variants:
        if "weights" not in params:
            params["weights"] = deepcopy(normalized_seed["weights"])
        params["seed_tag"] = normalized_seed.get("seed_tag")
        candidates.append(params)

    selected_threshold_variants = threshold_variants[:20]
    selected_weight_variants = [
        p for p in weight_variants[1:]
        if str(p.get("mutation_tag")) in {
            "trend_up",
            "momentum_up",
            "volume_up",
            "volume_momentum_combo",
            "trend_only",
            "momentum_only",
            "long_trend_short_momentum",
            "long_momentum_short_trend",
        }
    ]
    selected_profile_variants = profile_variants[:8]

    for threshold_params in selected_threshold_variants:
        for weight_params in selected_weight_variants:
            merged = _copy_params(threshold_params)
            merged["weights"] = deepcopy(weight_params["weights"])
            merged["seed_tag"] = normalized_seed.get("seed_tag")

            threshold_tag = threshold_params.get("mutation_tag", "threshold")
            weight_tag = weight_params.get("mutation_tag", "weight")
            merged["mutation_tag"] = f"{threshold_tag}+{weight_tag}"
            candidates.append(merged)

    for profile_params in selected_profile_variants:
        for weight_params in selected_weight_variants:
            merged = _copy_params(profile_params)
            merged["weights"] = deepcopy(weight_params["weights"])
            merged["seed_tag"] = normalized_seed.get("seed_tag")

            profile_tag = profile_params.get("mutation_tag", "profile")
            weight_tag = weight_params.get("mutation_tag", "weight")
            merged["mutation_tag"] = f"{profile_tag}+{weight_tag}"
            candidates.append(merged)

    for profile_params in selected_profile_variants[:4]:
        for threshold_params in selected_threshold_variants[:6]:
            merged = _copy_params(profile_params)
            for key, value in threshold_params.items():
                if key in {"weights", "mutation_tag", "seed_tag"}:
                    continue
                merged[key] = value

            merged["weights"] = deepcopy(normalized_seed["weights"])
            merged["seed_tag"] = normalized_seed.get("seed_tag")

            profile_tag = profile_params.get("mutation_tag", "profile")
            threshold_tag = threshold_params.get("mutation_tag", "threshold")
            merged["mutation_tag"] = f"{profile_tag}+{threshold_tag}"
            candidates.append(merged)

    return candidates


def _interleave_candidate_groups(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """
    功能：把多個 seed 的候選交錯輸出，避免前面的 seed 吃掉 max-candidates 配額。
    """
    merged: list[dict[str, Any]] = []
    max_len = max((len(group) for group in groups), default=0)

    for idx in range(max_len):
        for group in groups:
            if idx < len(group):
                merged.append(group[idx])

    return merged


def generate_param_candidates(
    *,
    base_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    功能：根據 base strategy 產生第八版候選參數組合。
    說明：
        - 新增真正獨立的 base search seeds
        - 不再只圍繞 ACTIVE 附近微調
        - 每個 seed 內再做 threshold / profile / weights / combo 搜尋
        - 改為 seed 交錯輸出，避免 seed_base_current 壟斷前段配額
        - 最後做全域 fingerprint 去重
    """
    seed_params_list = _build_seed_params(base_params)

    per_seed_candidates: list[list[dict[str, Any]]] = []
    for seed_params in seed_params_list:
        seed_candidates = _generate_candidates_from_seed(seed_params)
        per_seed_candidates.append(seed_candidates)

    interleaved_candidates = _interleave_candidate_groups(per_seed_candidates)
    valid_candidates = [params for params in interleaved_candidates if _is_valid_candidate(params)]
    deduped_candidates = _dedupe_candidates(valid_candidates)
    return deduped_candidates