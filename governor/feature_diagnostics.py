"""
Path: governor/feature_diagnostics.py
說明：feature diagnostics 治理決策。
"""

from __future__ import annotations


def build_feature_actions(summary_rows: list[dict]) -> list[dict]:
    actions: list[dict] = []

    for row in summary_rows:
        feature_key = str(row["feature_key"])
        diagnostic_score = float(row.get("diagnostic_score", 0.0))
        winner_count = int(row.get("winner_count", 0))
        loser_count = int(row.get("loser_count", 0))

        action = "KEEP"
        target_bias = 0.0
        reason_type = "NEUTRAL"
        reason_message = "feature 表現中性，維持不變"

        if diagnostic_score > 0 and winner_count >= 3:
            action = "INCREASE"
            target_bias = diagnostic_score
            reason_type = "POSITIVE_FEATURE"
            reason_message = "diagnostic_score > 0 且 winner_count >= 3，上調 feature bias"
        elif diagnostic_score < 0 and loser_count >= 5:
            action = "DECREASE"
            target_bias = diagnostic_score
            reason_type = "NEGATIVE_FEATURE"
            reason_message = "diagnostic_score < 0 且 loser_count >= 5，下調 feature bias"

        actions.append(
            {
                "feature_key": feature_key,
                "action": action,
                "target_bias": target_bias,
                "reason": {
                    "type": reason_type,
                    "message": reason_message,
                    "diagnostic_score": diagnostic_score,
                    "winner_count": winner_count,
                    "loser_count": loser_count,
                },
            }
        )

    return actions