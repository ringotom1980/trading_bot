"""
Path: evolver/scorer.py
說明：Candidate Scorer v3，強化 drawdown 懲罰，並加入過度交易懲罰。
"""

from __future__ import annotations

from typing import Any


def calculate_candidate_score(metrics: dict[str, Any]) -> float:
    """
    功能：依回測結果計算 candidate score。
    說明：
        第三版改為：
        - net_pnl 保留，但不讓它單獨主導排序
        - profit_factor 權重再提高
        - max_drawdown 懲罰再加重
        - total_trades 太少要扣分
        - total_trades 過多也扣分，避免過度交易型 candidate 排太前面
        - 對低 profit_factor 額外加罰，避免品質不足卻靠 pnl 撐分
    """
    net_pnl = float(metrics.get("net_pnl", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    total_trades = int(metrics.get("total_trades", 0))
    win_rate = float(metrics.get("win_rate", 0.0))

    low_trade_penalty = 0.0 if total_trades >= 12 else (12 - total_trades) * 1.8
    trade_count_bonus = min(total_trades, 45) * 0.06

    overtrade_penalty = 0.0
    if total_trades > 60:
        overtrade_penalty = (total_trades - 60) * 0.45

    low_pf_penalty = 0.0
    if profit_factor < 1.40:
        low_pf_penalty = (1.40 - profit_factor) * 18.0

    score = (
        net_pnl * 0.50
        + profit_factor * 20.0
        - max_drawdown * 0.50
        + win_rate * 6.0
        + trade_count_bonus
        - low_trade_penalty
        - overtrade_penalty
        - low_pf_penalty
    )

    return score