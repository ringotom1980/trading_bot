"""
Path: strategy/decision.py
說明：第一版決策模組，負責依 long_score、short_score 與目前持倉狀態輸出標準 decision。
"""

from __future__ import annotations

from typing import Any


DEFAULT_ENTRY_THRESHOLD = 0.60
DEFAULT_EXIT_THRESHOLD = 0.45
DEFAULT_REVERSE_THRESHOLD = 0.68
DEFAULT_REVERSE_GAP = 0.08


def build_decision_result(
    decision: str,
    decision_score: float,
    reason_code: str,
    reason_summary: str,
    long_score: float,
    short_score: float,
) -> dict[str, Any]:
    """
    功能：建立標準化 decision 輸出格式。
    參數：
        decision: 決策結果。
        decision_score: 主要決策分數。
        reason_code: 決策原因代碼。
        reason_summary: 決策原因摘要。
        long_score: 偏多分數。
        short_score: 偏空分數。
    回傳：
        決策結果字典。
    """
    return {
        "decision": decision,
        "decision_score": decision_score,
        "reason_code": reason_code,
        "reason_summary": reason_summary,
        "long_score": long_score,
        "short_score": short_score,
    }


def decide_without_position(long_score: float, short_score: float) -> dict[str, Any]:
    """
    功能：在目前無持倉時，依雙分數決定是否進場。
    參數：
        long_score: 偏多分數。
        short_score: 偏空分數。
    回傳：
        標準化決策結果字典。
    """
    if long_score >= DEFAULT_ENTRY_THRESHOLD and long_score > short_score + DEFAULT_REVERSE_GAP:
        return build_decision_result(
            decision="ENTER_LONG",
            decision_score=long_score,
            reason_code="ENTRY_SIGNAL",
            reason_summary="無持倉，long_score 達進場門檻且明顯強於 short_score",
            long_score=long_score,
            short_score=short_score,
        )

    if short_score >= DEFAULT_ENTRY_THRESHOLD and short_score > long_score + DEFAULT_REVERSE_GAP:
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


def decide_with_long_position(long_score: float, short_score: float) -> dict[str, Any]:
    """
    功能：在目前持有 LONG 時，依雙分數決定 HOLD 或 EXIT。
    參數：
        long_score: 偏多分數。
        short_score: 偏空分數。
    回傳：
        標準化決策結果字典。
    """
    if short_score >= DEFAULT_REVERSE_THRESHOLD and short_score > long_score + DEFAULT_REVERSE_GAP:
        return build_decision_result(
            decision="EXIT",
            decision_score=short_score,
            reason_code="REVERSE_SIGNAL",
            reason_summary="目前持有 LONG，但 short_score 達反向門檻，先退出等待下一輪反向",
            long_score=long_score,
            short_score=short_score,
        )

    if long_score < DEFAULT_EXIT_THRESHOLD:
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


def decide_with_short_position(long_score: float, short_score: float) -> dict[str, Any]:
    """
    功能：在目前持有 SHORT 時，依雙分數決定 HOLD 或 EXIT。
    參數：
        long_score: 偏多分數。
        short_score: 偏空分數。
    回傳：
        標準化決策結果字典。
    """
    if long_score >= DEFAULT_REVERSE_THRESHOLD and long_score > short_score + DEFAULT_REVERSE_GAP:
        return build_decision_result(
            decision="EXIT",
            decision_score=long_score,
            reason_code="REVERSE_SIGNAL",
            reason_summary="目前持有 SHORT，但 long_score 達反向門檻，先退出等待下一輪反向",
            long_score=long_score,
            short_score=short_score,
        )

    if short_score < DEFAULT_EXIT_THRESHOLD:
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
) -> dict[str, Any]:
    """
    功能：依雙分數與目前持倉方向輸出第一版決策。
    參數：
        long_score: 偏多分數。
        short_score: 偏空分數。
        current_position_side: 目前持倉方向，可為 LONG、SHORT 或 None。
    回傳：
        標準化決策結果字典。
    """
    if current_position_side is None:
        return decide_without_position(long_score, short_score)

    if current_position_side == "LONG":
        return decide_with_long_position(long_score, short_score)

    if current_position_side == "SHORT":
        return decide_with_short_position(long_score, short_score)

    raise ValueError(f"不支援的持倉方向：{current_position_side}")