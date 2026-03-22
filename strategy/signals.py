"""
Path: strategy/signals.py
說明：訊號評分模組，依 feature pack 與 strategy params 計算 long_score 與 short_score。
"""

from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS = {
    "long": {
        "close_vs_sma20_pct": 0.22,
        "close_vs_sma60_pct": 0.22,
        "slope_5": 0.18,
        "slope_10": 0.18,
        "volume_ratio_20": 0.20,
    },
    "short": {
        "close_vs_sma20_pct": 0.22,
        "close_vs_sma60_pct": 0.22,
        "slope_5": 0.18,
        "slope_10": 0.18,
        "volume_ratio_20": 0.20,
    },
}


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def _score_positive_ratio(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.5

    normalized = 0.5 + (value / scale) * 0.5
    return _clamp(normalized)


def _score_negative_ratio(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.5

    normalized = 0.5 + ((-value) / scale) * 0.5
    return _clamp(normalized)


def _build_component_scores(feature_pack: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    close_vs_sma20_pct = float(feature_pack["close_vs_sma20_pct"])
    close_vs_sma60_pct = float(feature_pack["close_vs_sma60_pct"])
    slope_5 = float(feature_pack["slope_5"])
    slope_10 = float(feature_pack["slope_10"])
    volume_ratio_20 = float(feature_pack["volume_ratio_20"])

    long_components = {
        "close_vs_sma20_pct": _score_positive_ratio(close_vs_sma20_pct, scale=0.03),
        "close_vs_sma60_pct": _score_positive_ratio(close_vs_sma60_pct, scale=0.05),
        "slope_5": _score_positive_ratio(slope_5, scale=300.0),
        "slope_10": _score_positive_ratio(slope_10, scale=500.0),
        "volume_ratio_20": _score_positive_ratio(volume_ratio_20 - 1.0, scale=1.0),
    }

    short_components = {
        "close_vs_sma20_pct": _score_negative_ratio(close_vs_sma20_pct, scale=0.03),
        "close_vs_sma60_pct": _score_negative_ratio(close_vs_sma60_pct, scale=0.05),
        "slope_5": _score_negative_ratio(slope_5, scale=300.0),
        "slope_10": _score_negative_ratio(slope_10, scale=500.0),
        "volume_ratio_20": _score_positive_ratio(volume_ratio_20 - 1.0, scale=1.0),
    }

    return long_components, short_components


def _resolve_weights(params: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    if not params:
        return DEFAULT_WEIGHTS

    raw_weights = params.get("weights")
    if not isinstance(raw_weights, dict):
        return DEFAULT_WEIGHTS

    long_weights = raw_weights.get("long")
    short_weights = raw_weights.get("short")

    if not isinstance(long_weights, dict) or not isinstance(short_weights, dict):
        return DEFAULT_WEIGHTS

    resolved = {
        "long": dict(DEFAULT_WEIGHTS["long"]),
        "short": dict(DEFAULT_WEIGHTS["short"]),
    }

    for key in resolved["long"]:
        if key in long_weights:
            resolved["long"][key] = float(long_weights[key])

    for key in resolved["short"]:
        if key in short_weights:
            resolved["short"][key] = float(short_weights[key])

    return resolved


def calculate_signal_scores(
    feature_pack: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
    """
    功能：依 feature pack 與 strategy params 計算 long_score / short_score。
    """
    long_components, short_components = _build_component_scores(feature_pack)
    weights = _resolve_weights(params)

    long_score = sum(
        long_components[key] * weights["long"][key]
        for key in weights["long"]
    )
    short_score = sum(
        short_components[key] * weights["short"][key]
        for key in weights["short"]
    )

    return {
        "long_score": _clamp(long_score),
        "short_score": _clamp(short_score),
    }