"""
Path: governor/family_manager.py
說明：family 層級的治理決策。
"""

from __future__ import annotations

from typing import Any


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def build_family_actions(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for row in summary_rows:
        family_key = str(row["family_key"])
        sample_count = int(row.get("sample_count", 0))
        pass_count = int(row.get("pass_count", 0))
        avg_rank_score = float(row.get("avg_rank_score", 0.0))
        pass_ratio = _safe_ratio(pass_count, sample_count)

        action = "KEEP"
        target_weight = 0.5
        reason_type = "INSUFFICIENT_DATA"
        reason_message = "sample_count 不足，先維持原樣"

        if sample_count >= 3 and pass_count == 0:
            action = "DECREASE"
            target_weight = 0.3
            reason_type = "ZERO_PASS"
            reason_message = "sample_count >= 3 且 pass_count = 0，下調 family 權重"
        elif sample_count >= 3 and pass_ratio >= 0.5 and avg_rank_score > 0:
            action = "INCREASE"
            target_weight = 0.7
            reason_type = "STRONG_FAMILY"
            reason_message = "pass_ratio >= 0.5 且 avg_rank_score > 0，上調 family 權重"
        else:
            action = "KEEP"
            target_weight = 0.5
            reason_type = "NEUTRAL"
            reason_message = "family 表現中性，維持權重"

        actions.append(
            {
                "family_key": family_key,
                "action": action,
                "target_weight": target_weight,
                "reason": {
                    "type": reason_type,
                    "message": reason_message,
                    "sample_count": sample_count,
                    "pass_count": pass_count,
                    "pass_ratio": pass_ratio,
                    "avg_rank_score": avg_rank_score,
                },
            }
        )

    return actions