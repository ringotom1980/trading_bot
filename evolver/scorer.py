"""
Path: evolver/scorer.py
說明：Candidate Scorer v4，加入 candidate gate，先判定是否合格，再進行排序。
"""

from __future__ import annotations

from typing import Any


def evaluate_candidate_gate(metrics: dict[str, Any]) -> tuple[bool, str | None]:
    """
    功能：先判定 candidate 是否達到最基本合格門檻。
    回傳：
        (is_qualified, reject_reason)
    """
    net_pnl = float(metrics.get("net_pnl", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    total_trades = int(metrics.get("total_trades", 0))
    win_rate = float(metrics.get("win_rate", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))

    if total_trades < 20:
        return False, "TOTAL_TRADES_TOO_LOW"

    if net_pnl <= 0:
        return False, "NET_PNL_NOT_POSITIVE"

    if profit_factor < 1.0:
        return False, "PROFIT_FACTOR_TOO_LOW"

    if win_rate < 0.25:
        return False, "WIN_RATE_TOO_LOW"

    if max_drawdown > net_pnl * 2.5:
        return False, "DRAWDOWN_TOO_HIGH"

    return True, None


def calculate_candidate_score(metrics: dict[str, Any]) -> float:
    """
    功能：依回測結果計算 candidate score。
    說明：
        - 先經過 gate；不合格 candidate 直接給極低分
        - 合格後再依品質排序
    """
    is_qualified, _ = evaluate_candidate_gate(metrics)
    if not is_qualified:
        return -999999.0

    net_pnl = float(metrics.get("net_pnl", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    total_trades = int(metrics.get("total_trades", 0))
    win_rate = float(metrics.get("win_rate", 0.0))

    trade_count_bonus = min(total_trades, 80) * 0.06

    overtrade_penalty = 0.0
    if total_trades > 120:
        overtrade_penalty = (total_trades - 120) * 0.15

    score = (
        net_pnl * 0.45
        + profit_factor * 35.0
        - max_drawdown * 0.30
        + win_rate * 18.0
        + trade_count_bonus
        - overtrade_penalty
    )

    return score