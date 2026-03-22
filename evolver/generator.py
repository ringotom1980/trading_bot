"""
Path: evolver/generator.py
說明：Candidate Generator v4，採偏保守的縮窄搜尋，優先降低噪音交易、壓回撤、提高 PF。
"""

from __future__ import annotations

from itertools import product
from typing import Any


def generate_param_candidates(
    *,
    base_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    功能：根據 base strategy 產生第四版候選參數組合。
    說明：
        - 改為偏保守搜尋
        - 提高進出場門檻
        - 拉大 cooldown
        - 保留 hard stop loss / take profit 搜尋
        - 其餘欄位沿用 base
    """
    entry_threshold_values = [0.60, 0.65, 0.70]
    exit_threshold_values = [0.45, 0.50, 0.55]
    reverse_threshold_values = [0.70, 0.75, 0.80]
    reverse_gap_values = [0.10, 0.12, 0.15]

    cooldown_bars_values = [2, 3, 4, 6]
    min_hold_bars_values = [3, 4, 6]
    max_bars_hold_values = [12, 24, 36]

    hard_stop_loss_pct_values = [0.01, 0.015, 0.02]
    take_profit_pct_values = [0.01, 0.015, 0.02, 0.03]

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

        if take_profit_pct <= 0:
            continue

        if take_profit_pct <= hard_stop_loss_pct:
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