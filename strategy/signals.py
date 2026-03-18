"""
Path: strategy/signals.py
說明：第一版訊號評分模組，負責依 feature pack 計算 long_score 與 short_score。
"""

from __future__ import annotations

from typing import Any


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    """
    功能：將數值限制在指定範圍內。
    參數：
        value: 原始數值。
        min_value: 最小值。
        max_value: 最大值。
    回傳：
        經限制後的數值。
    """
    return max(min_value, min(max_value, value))


def _score_positive_ratio(value: float, scale: float) -> float:
    """
    功能：將偏多特徵轉為 0~1 分數，值越大越偏多。
    參數：
        value: 原始特徵值。
        scale: 正規化尺度。
    回傳：
        0~1 分數。
    """
    if scale <= 0:
        return 0.5

    normalized = 0.5 + (value / scale) * 0.5
    return _clamp(normalized)


def _score_negative_ratio(value: float, scale: float) -> float:
    """
    功能：將偏空特徵轉為 0~1 分數，值越小越偏空。
    參數：
        value: 原始特徵值。
        scale: 正規化尺度。
    回傳：
        0~1 分數。
    """
    if scale <= 0:
        return 0.5

    normalized = 0.5 + ((-value) / scale) * 0.5
    return _clamp(normalized)


def calculate_signal_scores(feature_pack: dict[str, Any]) -> dict[str, float]:
    """
    功能：依 feature pack 計算第一版 long_score 與 short_score。
    參數：
        feature_pack: 特徵包字典。
    回傳：
        包含 long_score 與 short_score 的字典。
    """
    close_vs_sma20_pct = float(feature_pack["close_vs_sma20_pct"])
    close_vs_sma60_pct = float(feature_pack["close_vs_sma60_pct"])
    slope_5 = float(feature_pack["slope_5"])
    slope_10 = float(feature_pack["slope_10"])
    volume_ratio_20 = float(feature_pack["volume_ratio_20"])

    # 第一版先使用固定權重，後續再改成從 strategy_versions.params_json 讀取
    weights = {
        "close_vs_sma20_pct": 0.22,
        "close_vs_sma60_pct": 0.22,
        "slope_5": 0.18,
        "slope_10": 0.18,
        "volume_ratio_20": 0.20,
    }

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

    long_score = sum(long_components[key] * weights[key] for key in weights)
    short_score = sum(short_components[key] * weights[key] for key in weights)

    return {
        "long_score": _clamp(long_score),
        "short_score": _clamp(short_score),
    }