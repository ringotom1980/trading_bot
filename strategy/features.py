"""
Path: strategy/features.py
說明：Feature Pool v2，負責將 K 線資料轉為策略可用的 feature pack，供 runtime、backtest、candidate 共用。
"""

from __future__ import annotations

from datetime import datetime
from math import sqrt
from statistics import mean
from typing import Any


def _extract_closes(klines: list[dict[str, Any]]) -> list[float]:
    return [float(kline["close"]) for kline in klines]


def _extract_opens(klines: list[dict[str, Any]]) -> list[float]:
    return [float(kline["open"]) for kline in klines]


def _extract_highs(klines: list[dict[str, Any]]) -> list[float]:
    return [float(kline["high"]) for kline in klines]


def _extract_lows(klines: list[dict[str, Any]]) -> list[float]:
    return [float(kline["low"]) for kline in klines]


def _extract_volumes(klines: list[dict[str, Any]]) -> list[float]:
    return [float(kline["volume"]) for kline in klines]


def _simple_moving_average(values: list[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"資料不足，無法計算 SMA{window}")
    return mean(values[-window:])


def _ema(values: list[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"資料不足，無法計算 EMA{window}")

    alpha = 2 / (window + 1)
    ema_value = mean(values[:window])

    for value in values[window:]:
        ema_value = alpha * value + (1 - alpha) * ema_value

    return ema_value


def _linear_slope(values: list[float], window: int) -> float:
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
    if not values:
        return 0.0

    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return sqrt(variance)


def _pct_change(values: list[float], bars: int) -> float:
    if len(values) < bars + 1:
        raise ValueError(f"資料不足，無法計算 return_{bars}")

    prev_value = values[-(bars + 1)]
    curr_value = values[-1]

    if prev_value == 0:
        return 0.0

    return (curr_value - prev_value) / prev_value


def _avg_range_pct(klines: list[dict[str, Any]], window: int) -> float:
    if len(klines) < window:
        raise ValueError(f"資料不足，無法計算 range_pct_{window}_avg")

    values: list[float] = []
    for kline in klines[-window:]:
        high = float(kline["high"])
        low = float(kline["low"])
        close = float(kline["close"])

        if close == 0:
            values.append(0.0)
        else:
            values.append((high - low) / close)

    return mean(values)


def _to_bar_close_time_value(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)

    return int(value)


def _calculate_rsi(closes: list[float], window: int = 14) -> float:
    if len(closes) < window + 1:
        raise ValueError(f"資料不足，無法計算 RSI{window}")

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-window:]

    gains = [max(delta, 0.0) for delta in recent]
    losses = [max(-delta, 0.0) for delta in recent]

    avg_gain = mean(gains)
    avg_loss = mean(losses)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calculate_macd(closes: list[float]) -> tuple[float, float, float]:
    if len(closes) < 35:
        raise ValueError("資料不足，無法計算 MACD")

    macd_series: list[float] = []
    for idx in range(26, len(closes) + 1):
        window = closes[:idx]
        ema12 = _ema(window, 12)
        ema26 = _ema(window, 26)
        macd_series.append(ema12 - ema26)

    macd_dif = macd_series[-1]
    macd_dea = _ema(macd_series, 9) if len(macd_series) >= 9 else mean(macd_series)
    macd_hist = macd_dif - macd_dea

    return macd_dif, macd_dea, macd_hist


def _calculate_kd(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> tuple[float, float, float]:
    if len(closes) < window:
        raise ValueError(f"資料不足，無法計算 KD{window}")

    k_value = 50.0
    d_value = 50.0

    for idx in range(window - 1, len(closes)):
        high_window = max(highs[idx - window + 1: idx + 1])
        low_window = min(lows[idx - window + 1: idx + 1])
        close = closes[idx]

        if high_window == low_window:
            rsv = 50.0
        else:
            rsv = ((close - low_window) / (high_window - low_window)) * 100.0

        k_value = (2.0 / 3.0) * k_value + (1.0 / 3.0) * rsv
        d_value = (2.0 / 3.0) * d_value + (1.0 / 3.0) * k_value

    return k_value, d_value, k_value - d_value


def _calculate_atr_pct(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> float:
    if len(closes) < window + 1:
        raise ValueError(f"資料不足，無法計算 ATR{window}")

    true_ranges: list[float] = []
    for idx in range(1, len(closes)):
        high = highs[idx]
        low = lows[idx]
        prev_close = closes[idx - 1]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    atr = mean(true_ranges[-window:])
    latest_close = closes[-1]

    if latest_close == 0:
        return 0.0

    return atr / latest_close


def _classify_regime(
    *,
    sma20_vs_sma60_pct: float,
    slope_10: float,
    volatility_10: float,
    range_pct_5_avg: float,
) -> tuple[str, float]:
    trend_threshold = 0.008
    slope_threshold = 80.0
    chop_vol_threshold = 0.012
    chop_range_threshold = 0.018

    if sma20_vs_sma60_pct >= trend_threshold and slope_10 >= slope_threshold:
        return "TREND_UP", 1.0

    if sma20_vs_sma60_pct <= -trend_threshold and slope_10 <= -slope_threshold:
        return "TREND_DOWN", -1.0

    if volatility_10 <= chop_vol_threshold and range_pct_5_avg <= chop_range_threshold:
        return "RANGE", 0.0

    if slope_10 > 0:
        return "TREND_UP", 0.5

    if slope_10 < 0:
        return "TREND_DOWN", -0.5

    return "RANGE", 0.0


def calculate_feature_pack(symbol: str, interval: str, klines: list[dict[str, Any]]) -> dict[str, Any]:
    """
    功能：依 K 線資料計算 Feature Pool v2。
    參數：
        symbol: 交易標的。
        interval: K 線週期。
        klines: K 線資料列表，至少需 60 根。
    回傳：
        特徵包字典。
    """
    if len(klines) < 60:
        raise ValueError("資料不足，至少需要 60 根 K 線才能計算 Feature Pool v2")

    opens = _extract_opens(klines)
    highs = _extract_highs(klines)
    lows = _extract_lows(klines)
    closes = _extract_closes(klines)
    volumes = _extract_volumes(klines)

    latest = klines[-1]
    latest_open = float(latest["open"])
    latest_high = float(latest["high"])
    latest_low = float(latest["low"])
    latest_close = float(latest["close"])
    latest_volume = float(latest["volume"])

    sma5 = _simple_moving_average(closes, 5)
    sma10 = _simple_moving_average(closes, 10)
    sma20 = _simple_moving_average(closes, 20)
    sma60 = _simple_moving_average(closes, 60)

    close_vs_sma5_pct = 0.0 if sma5 == 0 else (latest_close - sma5) / sma5
    close_vs_sma10_pct = 0.0 if sma10 == 0 else (latest_close - sma10) / sma10
    close_vs_sma20_pct = 0.0 if sma20 == 0 else (latest_close - sma20) / sma20
    close_vs_sma60_pct = 0.0 if sma60 == 0 else (latest_close - sma60) / sma60

    sma5_vs_sma20_pct = 0.0 if sma20 == 0 else (sma5 - sma20) / sma20
    sma20_vs_sma60_pct = 0.0 if sma60 == 0 else (sma20 - sma60) / sma60

    return_1 = _pct_change(closes, 1)
    return_3 = _pct_change(closes, 3)
    return_5 = _pct_change(closes, 5)
    return_10 = _pct_change(closes, 10)

    slope_5 = _linear_slope(closes, 5)
    slope_10 = _linear_slope(closes, 10)

    range_pct = 0.0 if latest_close == 0 else (latest_high - latest_low) / latest_close
    range_pct_3_avg = _avg_range_pct(klines, 3)
    range_pct_5_avg = _avg_range_pct(klines, 5)

    returns_5 = _returns(closes[-6:])
    returns_10 = _returns(closes[-11:])
    returns_20 = _returns(closes[-21:])

    volatility_5 = _standard_deviation(returns_5)
    volatility_10 = _standard_deviation(returns_10)
    volatility_20 = _standard_deviation(returns_20)

    avg_volume_5 = _simple_moving_average(volumes, 5)
    avg_volume_10 = _simple_moving_average(volumes, 10)
    avg_volume_20 = _simple_moving_average(volumes, 20)

    volume_ratio_5 = 0.0 if avg_volume_5 == 0 else latest_volume / avg_volume_5
    volume_ratio_10 = 0.0 if avg_volume_10 == 0 else latest_volume / avg_volume_10
    volume_ratio_20 = 0.0 if avg_volume_20 == 0 else latest_volume / avg_volume_20

    volume_slope_5 = _linear_slope(volumes, 5)
    volume_slope_10 = _linear_slope(volumes, 10)

    body = latest_close - latest_open
    full_range = latest_high - latest_low
    upper_wick = latest_high - max(latest_open, latest_close)
    lower_wick = min(latest_open, latest_close) - latest_low

    body_pct = 0.0 if full_range == 0 else abs(body) / full_range
    upper_wick_pct = 0.0 if full_range == 0 else upper_wick / full_range
    lower_wick_pct = 0.0 if full_range == 0 else lower_wick / full_range
    close_position_in_bar = 0.0 if full_range == 0 else (latest_close - latest_low) / full_range

    bullish_bar_flag = 1.0 if latest_close > latest_open else 0.0
    bearish_bar_flag = 1.0 if latest_close < latest_open else 0.0

    rsi_14 = _calculate_rsi(closes, 14)
    macd_dif, macd_dea, macd_hist = _calculate_macd(closes)
    kd_k, kd_d, kd_diff = _calculate_kd(highs, lows, closes, 14)
    atr_14_pct = _calculate_atr_pct(highs, lows, closes, 14)
    regime, regime_score = _classify_regime(
        sma20_vs_sma60_pct=sma20_vs_sma60_pct,
        slope_10=slope_10,
        volatility_10=volatility_10,
        range_pct_5_avg=range_pct_5_avg,
    )

    return {
        "symbol": symbol,
        "interval": interval,
        "bar_close_time": _to_bar_close_time_value(latest["close_time"]),

        "close_vs_sma5_pct": close_vs_sma5_pct,
        "close_vs_sma10_pct": close_vs_sma10_pct,
        "close_vs_sma20_pct": close_vs_sma20_pct,
        "close_vs_sma60_pct": close_vs_sma60_pct,
        "sma5_vs_sma20_pct": sma5_vs_sma20_pct,
        "sma20_vs_sma60_pct": sma20_vs_sma60_pct,

        "return_1": return_1,
        "return_3": return_3,
        "return_5": return_5,
        "return_10": return_10,

        "slope_5": slope_5,
        "slope_10": slope_10,

        "range_pct": range_pct,
        "range_pct_3_avg": range_pct_3_avg,
        "range_pct_5_avg": range_pct_5_avg,
        "volatility_5": volatility_5,
        "volatility_10": volatility_10,
        "volatility_20": volatility_20,

        "volume_ratio_5": volume_ratio_5,
        "volume_ratio_10": volume_ratio_10,
        "volume_ratio_20": volume_ratio_20,
        "volume_slope_5": volume_slope_5,
        "volume_slope_10": volume_slope_10,

        "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "close_position_in_bar": close_position_in_bar,
        "bullish_bar_flag": bullish_bar_flag,
        "bearish_bar_flag": bearish_bar_flag,

        "rsi_14": rsi_14,
        "macd_dif": macd_dif,
        "macd_dea": macd_dea,
        "macd_hist": macd_hist,
        "kd_k": kd_k,
        "kd_d": kd_d,
        "kd_diff": kd_diff,
        "atr_14_pct": atr_14_pct,
        "regime": regime,
        "regime_score": regime_score,
    }