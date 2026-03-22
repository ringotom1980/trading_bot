"""
Path: evolver/scorer.py
說明：Candidate Scorer v2，負責根據 backtest metrics 產生排序分數。
"""

from __future__ import annotations

from typing import Any


def calculate_candidate_score(metrics: dict[str, Any]) -> float:
    """
    功能：依回測結果計算 candidate score。
    說明：
        第二版改為：
        - 降低 net_pnl 權重，避免單靠訓練期高 pnl 衝分
        - 提高 profit_factor 權重，偏好品質
        - 提高 drawdown 懲罰，偏好穩定
        - 提高 trade_count 下限要求，避免太少交易的偶然結果
    """
    net_pnl = float(metrics.get("net_pnl", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    total_trades = int(metrics.get("total_trades", 0))
    win_rate = float(metrics.get("win_rate", 0.0))

    trade_count_bonus = min(total_trades, 40) * 0.08
    trade_count_penalty = 0.0 if total_trades >= 12 else (12 - total_trades) * 1.5

    score = (
        net_pnl * 0.6
        + profit_factor * 18.0
        - max_drawdown * 0.35
        + win_rate * 8.0
        + trade_count_bonus
        - trade_count_penalty
    )

    return score