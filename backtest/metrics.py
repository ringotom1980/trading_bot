"""
Path: backtest/metrics.py
說明：Backtest v1 指標計算模組。
"""

from __future__ import annotations

from typing import Any


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def calculate_backtest_metrics(
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[float],
) -> dict[str, Any]:
    """
    功能：計算 Backtest v1 基本績效指標。
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
    }