"""
Path: strategy/signals.py
說明：訊號評分模組，依 feature pack 與 strategy params 計算 long_score 與 short_score。
"""

from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS = {
    "long": {
        "rsi_14": 0.08,
        "macd_hist": 0.16,
        "kd_diff": 0.08,
        "close_vs_sma20_pct": 0.13,
        "close_vs_sma60_pct": 0.13,
        "slope_5": 0.09,
        "slope_10": 0.10,
        "atr_14_pct": -0.04,
        "volatility_10": -0.03,
        "volume_ratio_20": 0.08,
        "volume_slope_5": 0.03,
        "regime_score": 0.15,
    },
    "short": {
        "rsi_14": 0.08,
        "macd_hist": 0.16,
        "kd_diff": 0.08,
        "close_vs_sma20_pct": 0.13,
        "close_vs_sma60_pct": 0.13,
        "slope_5": 0.09,
        "slope_10": 0.10,
        "atr_14_pct": -0.04,
        "volatility_10": -0.03,
        "volume_ratio_20": 0.08,
        "volume_slope_5": 0.03,
        "regime_score": 0.15,
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


def _score_centered_band(value: float, low: float, high: float, tolerance: float) -> float:
    if low > high:
        low, high = high, low

    if low <= value <= high:
        return 1.0

    if value < low:
        distance = low - value
    else:
        distance = value - high

    if tolerance <= 0:
        return 0.5

    return _clamp(1.0 - distance / tolerance)


def _score_rsi_long(value: float) -> float:
    return _score_centered_band(value=value, low=50.0, high=64.0, tolerance=18.0)


def _score_rsi_short(value: float) -> float:
    return _score_centered_band(value=value, low=36.0, high=50.0, tolerance=18.0)


def _score_volume_ratio(value: float) -> float:
    if value <= 0.95:
        return 0.05
    if value <= 1.05:
        return 0.25
    if value <= 1.15:
        return 0.50
    if value <= 1.35:
        return 0.75
    if value <= 1.70:
        return 0.92
    return 1.0


def _score_regime_long(regime_score: float) -> float:
    if regime_score >= 1.0:
        return 1.0
    if regime_score >= 0.5:
        return 0.82
    if regime_score > -0.5:
        return 0.18
    return 0.02


def _score_regime_short(regime_score: float) -> float:
    if regime_score <= -1.0:
        return 1.0
    if regime_score <= -0.5:
        return 0.82
    if regime_score < 0.5:
        return 0.18
    return 0.02


def _score_atr_quality(value: float) -> float:
    return _score_centered_band(value=value, low=0.0035, high=0.0180, tolerance=0.0150)


def _score_volatility_quality(value: float) -> float:
    return _score_centered_band(value=value, low=0.0025, high=0.0140, tolerance=0.0120)


def _build_component_scores(feature_pack: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    close_vs_sma20_pct = float(feature_pack["close_vs_sma20_pct"])
    close_vs_sma60_pct = float(feature_pack["close_vs_sma60_pct"])
    slope_5 = float(feature_pack["slope_5"])
    slope_10 = float(feature_pack["slope_10"])
    volume_ratio_20 = float(feature_pack["volume_ratio_20"])

    rsi_14 = float(feature_pack["rsi_14"])
    macd_hist = float(feature_pack["macd_hist"])
    kd_diff = float(feature_pack["kd_diff"])
    atr_14_pct = float(feature_pack["atr_14_pct"])
    volatility_10 = float(feature_pack["volatility_10"])
    volume_slope_5 = float(feature_pack["volume_slope_5"])
    regime_score = float(feature_pack["regime_score"])

    long_components = {
        "rsi_14": _score_rsi_long(rsi_14),
        "macd_hist": _score_positive_ratio(macd_hist, scale=20.0),
        "kd_diff": _score_positive_ratio(kd_diff, scale=5.0),
        "close_vs_sma20_pct": _score_positive_ratio(close_vs_sma20_pct, scale=0.010),
        "close_vs_sma60_pct": _score_positive_ratio(close_vs_sma60_pct, scale=0.018),
        "slope_5": _score_positive_ratio(slope_5, scale=45.0),
        "slope_10": _score_positive_ratio(slope_10, scale=70.0),
        "atr_14_pct": _score_atr_quality(atr_14_pct),
        "volatility_10": _score_volatility_quality(volatility_10),
        "volume_ratio_20": _score_volume_ratio(volume_ratio_20),
        "volume_slope_5": _score_positive_ratio(volume_slope_5, scale=1200.0),
        "regime_score": _score_regime_long(regime_score),
    }

    short_components = {
        "rsi_14": _score_rsi_short(rsi_14),
        "macd_hist": _score_negative_ratio(macd_hist, scale=20.0),
        "kd_diff": _score_negative_ratio(kd_diff, scale=5.0),
        "close_vs_sma20_pct": _score_negative_ratio(close_vs_sma20_pct, scale=0.010),
        "close_vs_sma60_pct": _score_negative_ratio(close_vs_sma60_pct, scale=0.018),
        "slope_5": _score_negative_ratio(slope_5, scale=45.0),
        "slope_10": _score_negative_ratio(slope_10, scale=70.0),
        "atr_14_pct": _score_atr_quality(atr_14_pct),
        "volatility_10": _score_volatility_quality(volatility_10),
        "volume_ratio_20": _score_volume_ratio(volume_ratio_20),
        "volume_slope_5": _score_negative_ratio(volume_slope_5, scale=1200.0),
        "regime_score": _score_regime_short(regime_score),
    }

    return long_components, short_components


def _normalize_weights(raw_weights: dict[str, float], allowed_keys: list[str]) -> dict[str, float]:
    filtered: dict[str, float] = {}

    for key in allowed_keys:
        value = raw_weights.get(key)
        if value is None:
            continue
        filtered[key] = max(0.000001, float(value))

    if not filtered:
        equal_weight = 1.0 / len(allowed_keys)
        return {key: equal_weight for key in allowed_keys}

    total = sum(filtered.values())

    if total <= 0:
        equal_weight = 1.0 / len(allowed_keys)
        return {key: equal_weight for key in allowed_keys}

    normalized = {
        key: filtered.get(key, 0.000001) / total
        for key in allowed_keys
    }

    normalized_total = sum(normalized.values())
    if normalized_total <= 0:
        equal_weight = 1.0 / len(allowed_keys)
        return {key: equal_weight for key in allowed_keys}

    return {
        key: normalized[key] / normalized_total
        for key in allowed_keys
    }


def _resolve_weights(params: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    allowed_keys = list(DEFAULT_WEIGHTS["long"].keys())

    if not params:
        return {
            "long": dict(DEFAULT_WEIGHTS["long"]),
            "short": dict(DEFAULT_WEIGHTS["short"]),
        }

    raw_weights = params.get("weights")
    if not isinstance(raw_weights, dict):
        return {
            "long": dict(DEFAULT_WEIGHTS["long"]),
            "short": dict(DEFAULT_WEIGHTS["short"]),
        }

    long_weights = raw_weights.get("long")
    short_weights = raw_weights.get("short")

    if not isinstance(long_weights, dict) or not isinstance(short_weights, dict):
        return {
            "long": dict(DEFAULT_WEIGHTS["long"]),
            "short": dict(DEFAULT_WEIGHTS["short"]),
        }

    return {
        "long": _normalize_weights(long_weights, allowed_keys),
        "short": _normalize_weights(short_weights, allowed_keys),
    }


def _apply_context_bias(
    *,
    long_score: float,
    short_score: float,
    feature_pack: dict[str, Any],
) -> tuple[float, float]:
    regime_score = float(feature_pack["regime_score"])
    slope_5 = float(feature_pack["slope_5"])
    slope_10 = float(feature_pack["slope_10"])
    macd_hist = float(feature_pack["macd_hist"])
    volume_ratio_20 = float(feature_pack["volume_ratio_20"])

    if -0.35 <= regime_score <= 0.35:
        long_score *= 0.78
        short_score *= 0.78

    if regime_score >= 0.60:
        long_score *= 1.08
        short_score *= 0.88
    elif regime_score <= -0.60:
        short_score *= 1.08
        long_score *= 0.88

    if slope_5 > 0 and slope_10 > 0 and macd_hist > 0:
        long_score *= 1.05
        short_score *= 0.92
    elif slope_5 < 0 and slope_10 < 0 and macd_hist < 0:
        short_score *= 1.05
        long_score *= 0.92

    if volume_ratio_20 < 1.0:
        long_score *= 0.92
        short_score *= 0.92
    elif volume_ratio_20 > 1.15:
        long_score *= 1.03
        short_score *= 1.03

    return _clamp(long_score), _clamp(short_score)


def calculate_signal_scores(
    feature_pack: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
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

    long_score, short_score = _apply_context_bias(
        long_score=long_score,
        short_score=short_score,
        feature_pack=feature_pack,
    )

    return {
        "long_score": _clamp(long_score),
        "short_score": _clamp(short_score),
    }