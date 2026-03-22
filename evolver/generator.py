"""
Path: evolver/generator.py
說明：Candidate Generator v1，負責從 base strategy params 產生一批候選參數組合。
"""

from __future__ import annotations

from itertools import product
from typing import Any


def generate_param_candidates(
    *,
    base_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    功能：根據 base strategy 產生第一版候選參數組合。
    說明：
        - 先只搜尋 decision thresholds
        - qty / fee_rate / warmup_bars 直接沿用 base
    """
    entry_threshold_values = [0.55, 0.60, 0.65]
    exit_threshold_values = [0.40, 0.45, 0.50]
    reverse_threshold_values = [0.65, 0.70, 0.75]
    reverse_gap_values = [0.08, 0.10, 0.12]

    candidates: list[dict[str, Any]] = []

    for entry_threshold, exit_threshold, reverse_threshold, reverse_gap in product(
        entry_threshold_values,
        exit_threshold_values,
        reverse_threshold_values,
        reverse_gap_values,
    ):
        if exit_threshold >= entry_threshold:
            continue

        if reverse_threshold < entry_threshold:
            continue

        params = dict(base_params)
        params["entry_threshold"] = entry_threshold
        params["exit_threshold"] = exit_threshold
        params["reverse_threshold"] = reverse_threshold
        params["reverse_gap"] = reverse_gap

        candidates.append(params)

    return candidates