"""
Path: evolver/generator.py
說明：Candidate Generator v6，加入 candidate 去重 / 指紋化，減少等價候選與無效 mutation。
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from strategy.signals import DEFAULT_WEIGHTS


THRESHOLD_FIELD_SPECS: dict[str, tuple[list[float], int]] = {
    "entry_threshold": ([-0.05, 0.05], 4),
    "exit_threshold": ([-0.05, 0.05], 4),
    "reverse_threshold": ([-0.05, 0.05], 4),
    "reverse_gap": ([-0.02, 0.02], 4),
    "hard_stop_loss_pct": ([-0.005, 0.005], 4),
    "take_profit_pct": ([-0.01, 0.01], 4),
}

INT_FIELD_SPECS: dict[str, list[int]] = {
    "cooldown_bars": [-1, 1],
    "min_hold_bars": [-1, 1],
    "max_bars_hold": [-12, 12],
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

    if float(normalized.get("hard_stop_loss_pct", 0.0)) <= 0:
        normalized["hard_stop_loss_pct"] = 0.015

    if float(normalized.get("take_profit_pct", 0.0)) <= 0:
        normalized["take_profit_pct"] = 0.03

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
    """
    功能：將 candidate 轉成穩定可比對的 canonical form。
    說明：
        - mutation_tag 不納入 fingerprint
        - 浮點數做固定 round
        - weights 做正規化後再 round
    """
    canonical = _copy_params(params)
    canonical.pop("mutation_tag", None)

    float_fields = [
        "entry_threshold",
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
                new_value = _clamp_int(base_value + delta, 2, 240)

            if new_value == base_value:
                continue

            params[field] = new_value
            params["mutation_tag"] = f"{field}:{delta:+}"
            variants.append(params)

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

    if take_profit_pct <= hard_stop_loss_pct:
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


def generate_param_candidates(
    *,
    base_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    功能：根據 base strategy 產生第六版候選參數組合。
    說明：
        - 保留 threshold 類微調
        - 新增 weights.long / weights.short 演化
        - 移除 +0.0 類無效 mutation
        - 加入 fingerprint 去重
    """
    normalized_base = _apply_safe_defaults(base_params)
    normalized_base["weights"] = _build_weight_variants(normalized_base)[0]["weights"]

    weight_variants = _build_weight_variants(normalized_base)
    threshold_variants = _build_threshold_variants(normalized_base)

    candidates: list[dict[str, Any]] = []
    candidates.append(normalized_base)

    # 純權重變化
    for params in weight_variants[1:]:
        candidates.append(params)

    # 純 threshold 變化
    for params in threshold_variants:
        if "weights" not in params:
            params["weights"] = deepcopy(normalized_base["weights"])
        candidates.append(params)

    # 少量 threshold + weight 組合
    selected_threshold_variants = threshold_variants[:12]
    selected_weight_variants = weight_variants[1:7]

    for threshold_params in selected_threshold_variants:
        for weight_params in selected_weight_variants:
            merged = _copy_params(threshold_params)
            merged["weights"] = deepcopy(weight_params["weights"])

            threshold_tag = threshold_params.get("mutation_tag", "threshold")
            weight_tag = weight_params.get("mutation_tag", "weight")
            merged["mutation_tag"] = f"{threshold_tag}+{weight_tag}"

            candidates.append(merged)

    valid_candidates = [params for params in candidates if _is_valid_candidate(params)]
    deduped_candidates = _dedupe_candidates(valid_candidates)
    return deduped_candidates