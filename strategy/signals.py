"""
Path: strategy/signals.py
說明：訊號評分模組，依 feature pack 與 strategy params 計算 long_score 與 short_score。
"""

from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS = {
    "long": {
        "rsi_14": 0.10,
        "macd_hist": 0.14,
        "kd_diff": 0.08,
        "close_vs_sma20_pct": 0.12,
        "close_vs_sma60_pct": 0.12,
        "slope_5": 0.10,
        "slope_10": 0.10,
        "atr_14_pct": -0.05,
        "volatility_10": -0.04,
        "volume_ratio_20": 0.07,
        "volume_slope_5": 0.04,
        "regime_score": 0.12,
    },
    "short": {
        "rsi_14": 0.10,
        "macd_hist": 0.14,
        "kd_diff": 0.08,
        "close_vs_sma20_pct": 0.12,
        "close_vs_sma60_pct": 0.12,
        "slope_5": 0.10,
        "slope_10": 0.10,
        "atr_14_pct": -0.05,
        "volatility_10": -0.04,
        "volume_ratio_20": 0.07,
        "volume_slope_5": 0.04,
        "regime_score": 0.12,
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


def _score_rsi_long(value: float) -> float:
    # RSI 偏多但避免過熱，50~65 較佳
    if value <= 50:
        return _score_positive_ratio(value - 50.0, 20.0)
    return _score_negative_ratio(value - 65.0, 35.0)


def _score_rsi_short(value: float) -> float:
    # RSI 偏空但避免過冷，35~50 較佳
    if value >= 50:
        return _score_negative_ratio(value - 50.0, 20.0)
    return _score_positive_ratio(35.0 - value, 35.0)


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
        "macd_hist": _score_positive_ratio(macd_hist, scale=150.0),
        "kd_diff": _score_positive_ratio(kd_diff, scale=20.0),
        "close_vs_sma20_pct": _score_positive_ratio(close_vs_sma20_pct, scale=0.03),
        "close_vs_sma60_pct": _score_positive_ratio(close_vs_sma60_pct, scale=0.05),
        "slope_5": _score_positive_ratio(slope_5, scale=300.0),
        "slope_10": _score_positive_ratio(slope_10, scale=500.0),
        "atr_14_pct": _score_negative_ratio(atr_14_pct, scale=0.03),
        "volatility_10": _score_negative_ratio(volatility_10, scale=0.03),
        "volume_ratio_20": _score_positive_ratio(volume_ratio_20 - 1.0, scale=1.0),
        "volume_slope_5": _score_positive_ratio(volume_slope_5, scale=20000.0),
        "regime_score": _score_positive_ratio(regime_score, scale=1.0),
    }

    short_components = {
        "rsi_14": _score_rsi_short(rsi_14),
        "macd_hist": _score_negative_ratio(macd_hist, scale=150.0),
        "kd_diff": _score_negative_ratio(kd_diff, scale=20.0),
        "close_vs_sma20_pct": _score_negative_ratio(close_vs_sma20_pct, scale=0.03),
        "close_vs_sma60_pct": _score_negative_ratio(close_vs_sma60_pct, scale=0.05),
        "slope_5": _score_negative_ratio(slope_5, scale=300.0),
        "slope_10": _score_negative_ratio(slope_10, scale=500.0),
        "atr_14_pct": _score_negative_ratio(atr_14_pct, scale=0.03),
        "volatility_10": _score_negative_ratio(volatility_10, scale=0.03),
        "volume_ratio_20": _score_positive_ratio(volume_ratio_20 - 1.0, scale=1.0),
        "volume_slope_5": _score_negative_ratio(volume_slope_5, scale=20000.0),
        "regime_score": _score_negative_ratio(regime_score, scale=1.0),
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