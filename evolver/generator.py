"""
Path: evolver/generator.py
說明：Candidate Generator v3，從 base strategy params 產生候選參數組合。
"""

from __future__ import annotations

from itertools import product
from typing import Any


def generate_param_candidates(
    *,
    base_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    功能：根據 base strategy 產生第三版候選參數組合。
    說明：
        - 搜尋 decision thresholds
        - 搜尋 cooldown / hold 管理參數
        - 搜尋 hard stop loss / take profit
        - qty / fee_rate / weights 等其餘欄位沿用 base
    """
    entry_threshold_values = [0.55, 0.60, 0.65]
    exit_threshold_values = [0.40, 0.45, 0.50]
    reverse_threshold_values = [0.65, 0.70]
    reverse_gap_values = [0.08, 0.12]

    cooldown_bars_values = [1, 2, 3]
    min_hold_bars_values = [2, 3, 4]
    max_bars_hold_values = [12, 24, 36]

    hard_stop_loss_pct_values = [0.01, 0.015, 0.02]
    take_profit_pct_values = [0.0, 0.01, 0.015, 0.02]

    candidates: list[dict[str, Any]] = []

    for (
        entry_threshold,
        exit_threshold,
        reverse_threshold,
        reverse_gap,
        cooldown_bars,
        min_hold_bars,
        max_bars_hold,
        hard_stop_loss_pct,
        take_profit_pct,
    ) in product(
        entry_threshold_values,
        exit_threshold_values,
        reverse_threshold_values,
        reverse_gap_values,
        cooldown_bars_values,
        min_hold_bars_values,
        max_bars_hold_values,
        hard_stop_loss_pct_values,
        take_profit_pct_values,
    ):
        if exit_threshold >= entry_threshold:
            continue

        if reverse_threshold < entry_threshold:
            continue

        if min_hold_bars >= max_bars_hold:
            continue

        if hard_stop_loss_pct <= 0:
            continue

        if take_profit_pct > 0 and take_profit_pct <= hard_stop_loss_pct * 0.5:
            continue

        params = dict(base_params)
        params["entry_threshold"] = entry_threshold
        params["exit_threshold"] = exit_threshold
        params["reverse_threshold"] = reverse_threshold
        params["reverse_gap"] = reverse_gap
        params["cooldown_bars"] = cooldown_bars
        params["min_hold_bars"] = min_hold_bars
        params["max_bars_hold"] = max_bars_hold
        params["hard_stop_loss_pct"] = hard_stop_loss_pct
        params["take_profit_pct"] = take_profit_pct

        candidates.append(params)

    return candidates