"""
Path: strategy/decision.py
說明：決策模組，依 long_score、short_score、目前持倉與 strategy params 輸出標準 decision。
"""

from __future__ import annotations

from typing import Any


DEFAULT_ENTRY_THRESHOLD = 0.60
DEFAULT_EXIT_THRESHOLD = 0.45
DEFAULT_REVERSE_THRESHOLD = 0.68
DEFAULT_REVERSE_GAP = 0.08
DEFAULT_EXIT_GAP = 0.03


def _resolve_thresholds(params: dict[str, Any] | None) -> dict[str, float]:
    if not params:
        return {
            "entry_threshold": DEFAULT_ENTRY_THRESHOLD,
            "exit_threshold": DEFAULT_EXIT_THRESHOLD,
            "reverse_threshold": DEFAULT_REVERSE_THRESHOLD,
            "reverse_gap": DEFAULT_REVERSE_GAP,
            "exit_gap": DEFAULT_EXIT_GAP,
        }

    return {
        "entry_threshold": float(params.get("entry_threshold", DEFAULT_ENTRY_THRESHOLD)),
        "exit_threshold": float(params.get("exit_threshold", DEFAULT_EXIT_THRESHOLD)),
        "reverse_threshold": float(params.get("reverse_threshold", DEFAULT_REVERSE_THRESHOLD)),
        "reverse_gap": float(params.get("reverse_gap", DEFAULT_REVERSE_GAP)),
        "exit_gap": float(params.get("exit_gap", DEFAULT_EXIT_GAP)),
    }


def build_decision_result(
    decision: str,
    decision_score: float,
    reason_code: str,
    reason_summary: str,
    long_score: float,
    short_score: float,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "decision_score": decision_score,
        "reason_code": reason_code,
        "reason_summary": reason_summary,
        "long_score": long_score,
        "short_score": short_score,
    }


def decide_without_position(
    long_score: float,
    short_score: float,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    entry_threshold = thresholds["entry_threshold"]
    reverse_gap = thresholds["reverse_gap"]

    if long_score >= entry_threshold and long_score > short_score + reverse_gap:
        return build_decision_result(
            decision="ENTER_LONG",
            decision_score=long_score,
            reason_code="ENTRY_SIGNAL",
            reason_summary="無持倉，long_score 達進場門檻且明顯強於 short_score",
            long_score=long_score,
            short_score=short_score,
        )

    if short_score >= entry_threshold and short_score > long_score + reverse_gap:
        return build_decision_result(
            decision="ENTER_SHORT",
            decision_score=short_score,
            reason_code="ENTRY_SIGNAL",
            reason_summary="無持倉，short_score 達進場門檻且明顯強於 long_score",
            long_score=long_score,
            short_score=short_score,
        )

    return build_decision_result(
        decision="WAIT",
        decision_score=max(long_score, short_score),
        reason_code="NO_SIGNAL",
        reason_summary="無持倉，但雙分數未達有效進場條件",
        long_score=long_score,
        short_score=short_score,
    )


def decide_with_long_position(
    long_score: float,
    short_score: float,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    reverse_threshold = thresholds["reverse_threshold"]
    reverse_gap = thresholds["reverse_gap"]
    exit_threshold = thresholds["exit_threshold"]
    exit_gap = thresholds["exit_gap"]

    if short_score >= reverse_threshold and short_score > long_score + reverse_gap:
        return build_decision_result(
            decision="EXIT",
            decision_score=short_score,
            reason_code="REVERSE_SIGNAL",
            reason_summary="目前持有 LONG，但 short_score 達反向門檻，先退出等待下一輪反向",
            long_score=long_score,
            short_score=short_score,
        )

    if long_score <= short_score + exit_gap:
        return build_decision_result(
            decision="EXIT",
            decision_score=long_score,
            reason_code="EDGE_LOST",
            reason_summary="目前持有 LONG，但 long 優勢已明顯收斂，先退出",
            long_score=long_score,
            short_score=short_score,
        )

    if long_score < exit_threshold:
        return build_decision_result(
            decision="EXIT",
            decision_score=long_score,
            reason_code="EXIT_SIGNAL",
            reason_summary="目前持有 LONG，但 long_score 已跌破出場門檻",
            long_score=long_score,
            short_score=short_score,
        )

    return build_decision_result(
        decision="HOLD",
        decision_score=long_score,
        reason_code="NO_SIGNAL",
        reason_summary="目前持有 LONG，long_score 仍具支撐，維持持倉",
        long_score=long_score,
        short_score=short_score,
    )


def decide_with_short_position(
    long_score: float,
    short_score: float,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    reverse_threshold = thresholds["reverse_threshold"]
    reverse_gap = thresholds["reverse_gap"]
    exit_threshold = thresholds["exit_threshold"]
    exit_gap = thresholds["exit_gap"]

    if long_score >= reverse_threshold and long_score > short_score + reverse_gap:
        return build_decision_result(
            decision="EXIT",
            decision_score=long_score,
            reason_code="REVERSE_SIGNAL",
            reason_summary="目前持有 SHORT，但 long_score 達反向門檻，先退出等待下一輪反向",
            long_score=long_score,
            short_score=short_score,
        )

    if short_score <= long_score + exit_gap:
        return build_decision_result(
            decision="EXIT",
            decision_score=short_score,
            reason_code="EDGE_LOST",
            reason_summary="目前持有 SHORT，但 short 優勢已明顯收斂，先退出",
            long_score=long_score,
            short_score=short_score,
        )

    if short_score < exit_threshold:
        return build_decision_result(
            decision="EXIT",
            decision_score=short_score,
            reason_code="EXIT_SIGNAL",
            reason_summary="目前持有 SHORT，但 short_score 已跌破出場門檻",
            long_score=long_score,
            short_score=short_score,
        )

    return build_decision_result(
        decision="HOLD",
        decision_score=short_score,
        reason_code="NO_SIGNAL",
        reason_summary="目前持有 SHORT，short_score 仍具支撐，維持持倉",
        long_score=long_score,
        short_score=short_score,
    )


def calculate_decision(
    long_score: float,
    short_score: float,
    current_position_side: str | None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thresholds = _resolve_thresholds(params)

    if current_position_side is None:
        return decide_without_position(long_score, short_score, thresholds)

    if current_position_side == "LONG":
        return decide_with_long_position(long_score, short_score, thresholds)

    if current_position_side == "SHORT":
        return decide_with_short_position(long_score, short_score, thresholds)

    raise ValueError(f"不支援的持倉方向：{current_position_side}")