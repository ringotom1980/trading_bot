"""
Path: strategy/features.py
說明：第一版特徵計算模組，負責將 K 線資料轉為策略可用的 feature pack。
"""

from __future__ import annotations

from math import sqrt
from statistics import mean
from typing import Any


def _extract_closes(klines: list[dict[str, Any]]) -> list[float]:
    """
    功能：從 K 線資料中取出收盤價序列。
    參數：
        klines: K 線資料列表。
    回傳：
        收盤價列表。
    """
    return [float(kline["close"]) for kline in klines]


def _extract_volumes(klines: list[dict[str, Any]]) -> list[float]:
    """
    功能：從 K 線資料中取出成交量序列。
    參數：
        klines: K 線資料列表。
    回傳：
        成交量列表。
    """
    return [float(kline["volume"]) for kline in klines]


def _simple_moving_average(values: list[float], window: int) -> float:
    """
    功能：計算簡單移動平均。
    參數：
        values: 數值序列。
        window: 視窗大小。
    回傳：
        SMA 數值。
    """
    if len(values) < window:
        raise ValueError(f"資料不足，無法計算 SMA{window}")

    return mean(values[-window:])


def _linear_slope(values: list[float], window: int) -> float:
    """
    功能：以最小平方法計算最近 window 筆資料斜率。
    參數：
        values: 數值序列。
        window: 視窗大小。
    回傳：
        斜率值。
    """
    if len(values) < window:
        raise ValueError(f"資料不足，無法計算 slope_{window}")

    y = values[-window:]
    x = list(range(window))

    x_mean = mean(x)
    y_mean = mean(y)

    numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    denominator = sum((xi - x_mean) ** 2 for xi in x)

    if denominator == 0:
        return 0.0

    return numerator / denominator


def _returns(values: list[float]) -> list[float]:
    """
    功能：計算相鄰收盤價報酬率序列。
    參數：
        values: 收盤價序列。
    回傳：
        報酬率列表。
    """
    if len(values) < 2:
        return []

    result: list[float] = []
    for idx in range(1, len(values)):
        prev_value = values[idx - 1]
        curr_value = values[idx]

        if prev_value == 0:
            result.append(0.0)
        else:
            result.append((curr_value - prev_value) / prev_value)

    return result


def _standard_deviation(values: list[float]) -> float:
    """
    功能：計算標準差。
    參數：
        values: 數值序列。
    回傳：
        標準差數值。
    """
    if not values:
        return 0.0

    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return sqrt(variance)


def calculate_feature_pack(symbol: str, interval: str, klines: list[dict[str, Any]]) -> dict[str, Any]:
    """
    功能：依 K 線資料計算第一版特徵包。
    參數：
        symbol: 交易標的。
        interval: K 線週期。
        klines: K 線資料列表，至少需 60 根。
    回傳：
        特徵包字典。
    """
    if len(klines) < 60:
        raise ValueError("資料不足，至少需要 60 根 K 線才能計算第一版特徵")

    closes = _extract_closes(klines)
    volumes = _extract_volumes(klines)

    latest = klines[-1]
    latest_close = float(latest["close"])
    latest_high = float(latest["high"])
    latest_low = float(latest["low"])
    latest_volume = float(latest["volume"])

    sma20 = _simple_moving_average(closes, 20)
    sma60 = _simple_moving_average(closes, 60)

    close_vs_sma20_pct = 0.0 if sma20 == 0 else (latest_close - sma20) / sma20
    close_vs_sma60_pct = 0.0 if sma60 == 0 else (latest_close - sma60) / sma60

    slope_5 = _linear_slope(closes, 5)
    slope_10 = _linear_slope(closes, 10)

    range_pct = 0.0 if latest_close == 0 else (latest_high - latest_low) / latest_close

    returns_10 = _returns(closes[-10:])
    volatility_10 = _standard_deviation(returns_10)

    avg_volume_20 = _simple_moving_average(volumes, 20)
    volume_ratio_20 = 0.0 if avg_volume_20 == 0 else latest_volume / avg_volume_20
    volume_slope_5 = _linear_slope(volumes, 5)

    return {
        "symbol": symbol,
        "interval": interval,
        "bar_close_time": int(latest["close_time"]),
        "close_vs_sma20_pct": close_vs_sma20_pct,
        "close_vs_sma60_pct": close_vs_sma60_pct,
        "slope_5": slope_5,
        "slope_10": slope_10,
        "range_pct": range_pct,
        "volatility_10": volatility_10,
        "volume_ratio_20": volume_ratio_20,
        "volume_slope_5": volume_slope_5,
    }