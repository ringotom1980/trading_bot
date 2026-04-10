"""
Path: backtest/metrics.py
說明：Backtest v2 指標計算模組，加入交易診斷與賺賠交易特徵分布統計。
"""

from __future__ import annotations

from typing import Any


DIAGNOSTIC_FEATURE_KEYS = [
    "rsi_14",
    "macd_hist",
    "kd_diff",
    "close_vs_sma20_pct",
    "close_vs_sma60_pct",
    "slope_5",
    "slope_10",
    "atr_14_pct",
    "volatility_10",
    "volume_ratio_20",
    "volume_slope_5",
    "regime_score",
]


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_trade_bucket_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "count": 0,
            "avg_net_pnl": 0.0,
            "avg_bars_held": 0.0,
            "avg_entry_long_score": 0.0,
            "avg_entry_short_score": 0.0,
            "feature_avgs": {},
            "regime_counts": {},
        }

    feature_avgs: dict[str, float] = {}
    regime_counts: dict[str, int] = {}

    for key in DIAGNOSTIC_FEATURE_KEYS:
        values: list[float] = []
        for trade in trades:
            snapshot = dict(trade.get("entry_feature_snapshot") or {})
            value = snapshot.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        feature_avgs[key] = _safe_mean(values)

    for trade in trades:
        snapshot = dict(trade.get("entry_feature_snapshot") or {})
        regime = snapshot.get("regime")
        if regime is None:
            continue
        regime_text = str(regime)
        regime_counts[regime_text] = regime_counts.get(regime_text, 0) + 1

    return {
        "count": len(trades),
        "avg_net_pnl": _safe_mean([float(t.get("net_pnl", 0.0)) for t in trades]),
        "avg_bars_held": _safe_mean([float(t.get("bars_held", 0)) for t in trades]),
        "avg_entry_long_score": _safe_mean([float(t.get("entry_long_score", 0.0)) for t in trades]),
        "avg_entry_short_score": _safe_mean([float(t.get("entry_short_score", 0.0)) for t in trades]),
        "feature_avgs": feature_avgs,
        "regime_counts": regime_counts,
    }


def _build_feature_diagnostics(
    winners: list[dict[str, Any]],
    losers: list[dict[str, Any]],
) -> dict[str, Any]:
    winner_summary = _build_trade_bucket_summary(winners)
    loser_summary = _build_trade_bucket_summary(losers)

    feature_delta: dict[str, float] = {}
    for key in DIAGNOSTIC_FEATURE_KEYS:
        winner_value = float(winner_summary["feature_avgs"].get(key, 0.0))
        loser_value = float(loser_summary["feature_avgs"].get(key, 0.0))
        feature_delta[key] = winner_value - loser_value

    return {
        "winners": winner_summary,
        "losers": loser_summary,
        "feature_delta": feature_delta,
    }


def calculate_backtest_metrics(
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[float],
) -> dict[str, Any]:
    """
    功能：計算 Backtest v2 基本績效指標與交易診斷。
    """
    total_trades = len(trades)

    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
            "avg_trade_pnl": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "expectancy": 0.0,
            "feature_diagnostics": {
                "winners": {
                    "count": 0,
                    "avg_net_pnl": 0.0,
                    "avg_bars_held": 0.0,
                    "avg_entry_long_score": 0.0,
                    "avg_entry_short_score": 0.0,
                    "feature_avgs": {},
                    "regime_counts": {},
                },
                "losers": {
                    "count": 0,
                    "avg_net_pnl": 0.0,
                    "avg_bars_held": 0.0,
                    "avg_entry_long_score": 0.0,
                    "avg_entry_short_score": 0.0,
                    "feature_avgs": {},
                    "regime_counts": {},
                },
                "feature_delta": {},
            },
        }

    gross_pnl = sum(float(t["gross_pnl"]) for t in trades)
    fees = sum(float(t["fees"]) for t in trades)
    net_pnl = sum(float(t["net_pnl"]) for t in trades)

    winners = [t for t in trades if float(t["net_pnl"]) > 0]
    losers = [t for t in trades if float(t["net_pnl"]) < 0]

    win_rate = _safe_div(len(winners), total_trades)

    gross_profit = sum(float(t["net_pnl"]) for t in winners)
    gross_loss = abs(sum(float(t["net_pnl"]) for t in losers))
    profit_factor = 0.0 if gross_loss == 0 else gross_profit / gross_loss

    avg_trade_pnl = _safe_div(net_pnl, total_trades)
    expectancy = avg_trade_pnl

    peak = 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    feature_diagnostics = _build_feature_diagnostics(winners, losers)

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "avg_trade_pnl": avg_trade_pnl,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "expectancy": expectancy,
        "feature_diagnostics": feature_diagnostics,
    }