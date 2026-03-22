"""
Path: evolver/scorer.py
說明：Candidate Scorer v1，負責根據 backtest metrics 產生排序分數。
"""

from __future__ import annotations

from typing import Any


def calculate_candidate_score(metrics: dict[str, Any]) -> float:
    """
    功能：依回測結果計算 candidate score。
    說明：
        第一版採簡單加權：
        - net_pnl 越高越好
        - profit_factor 越高越好
        - max_drawdown 越低越好
        - total_trades 太少會扣分
    """
    net_pnl = float(metrics.get("net_pnl", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    total_trades = int(metrics.get("total_trades", 0))

    trade_count_bonus = min(total_trades, 30) * 0.05
    trade_count_penalty = 0.0 if total_trades >= 5 else (5 - total_trades) * 1.0

    score = (
        net_pnl * 1.0
        + profit_factor * 10.0
        - max_drawdown * 0.2
        + trade_count_bonus
        - trade_count_penalty
    )

    return score