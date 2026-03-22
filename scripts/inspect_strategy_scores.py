"""
Path: scripts/inspect_strategy_scores.py
說明：策略分數觀察工具，抓取最近 N 根已收線 K 棒，逐根重算 feature / signal / decision，
用來觀察 long_score、short_score、decision 與 entry_threshold 的差距。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.logging import setup_logging
from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from services.strategy_service import load_active_strategy
from storage.db import connection_scope, test_connection
from strategy.decision import build_decision_result
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores


def _ms_to_local_str(ms: int) -> str:
    """
    功能：將毫秒時間戳轉為本地可讀字串。
    """
    dt = datetime.fromtimestamp(ms / 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _calculate_decision_with_params(
    *,
    long_score: float,
    short_score: float,
    current_position_side: str | None,
    entry_threshold: float,
    exit_threshold: float,
    reverse_threshold: float,
    reverse_gap: float,
) -> dict[str, Any]:
    """
    功能：使用 ACTIVE strategy 的 params_json 門檻，模擬 runtime 真正 decision 邏輯。
    """
    if current_position_side is None:
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

    if current_position_side == "LONG":
        if short_score >= reverse_threshold and short_score > long_score + reverse_gap:
            return build_decision_result(
                decision="EXIT",
                decision_score=short_score,
                reason_code="REVERSE_SIGNAL",
                reason_summary="目前持有 LONG，但 short_score 達反向門檻，先退出等待下一輪反向",
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

    if current_position_side == "SHORT":
        if long_score >= reverse_threshold and long_score > short_score + reverse_gap:
            return build_decision_result(
                decision="EXIT",
                decision_score=long_score,
                reason_code="REVERSE_SIGNAL",
                reason_summary="目前持有 SHORT，但 long_score 達反向門檻，先退出等待下一輪反向",
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

    raise ValueError(f"不支援的持倉方向：{current_position_side}")


def _build_row(
    *,
    klines_window: list[dict[str, Any]],
    current_position_side: str | None,
    entry_threshold: float,
    exit_threshold: float,
    reverse_threshold: float,
    reverse_gap: float,
) -> dict[str, Any]:
    """
    功能：對單一 bar 視窗計算 feature / signal / decision。
    """
    feature_pack = calculate_feature_pack(
        symbol="BTCUSDT",
        interval="15m",
        klines=klines_window,
    )

    signal_scores = calculate_signal_scores(feature_pack)
    decision_result = _calculate_decision_with_params(
        long_score=signal_scores["long_score"],
        short_score=signal_scores["short_score"],
        current_position_side=current_position_side,
        entry_threshold=entry_threshold,
        exit_threshold=exit_threshold,
        reverse_threshold=reverse_threshold,
        reverse_gap=reverse_gap,
    )

    latest = klines_window[-1]
    long_score = float(signal_scores["long_score"])
    short_score = float(signal_scores["short_score"])

    return {
        "bar_close_time": _ms_to_local_str(int(latest["close_time"])),
        "close": float(latest["close"]),
        "long_score": long_score,
        "short_score": short_score,
        "decision": str(decision_result["decision"]),
        "decision_score": float(decision_result["decision_score"]),
        "long_gap_to_entry": entry_threshold - long_score,
        "short_gap_to_entry": entry_threshold - short_score,
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    """
    功能：將結果以簡單表格輸出。
    """
    headers = [
        "bar_close_time",
        "close",
        "long_score",
        "short_score",
        "decision",
        "decision_score",
        "long_gap_to_entry",
        "short_gap_to_entry",
    ]

    widths: dict[str, int] = {}
    for header in headers:
        widths[header] = max(
            len(header),
            *(len(f"{row[header]:.6f}") if isinstance(row[header],
              float) else len(str(row[header])) for row in rows),
        )

    def _fmt_value(header: str, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.6f}".rjust(widths[header])
        return str(value).ljust(widths[header])

    header_line = " | ".join(header.ljust(
        widths[header]) for header in headers)
    split_line = "-+-".join("-" * widths[header] for header in headers)

    print(header_line)
    print(split_line)

    for row in rows:
        print(" | ".join(_fmt_value(
            header, row[header]) for header in headers))


def main() -> None:
    """
    功能：主程式入口。
    用法：
        python scripts/inspect_strategy_scores.py [bars]
    範例：
        python scripts/inspect_strategy_scores.py 20
    """
    setup_logging()

    bars = 20
    if len(sys.argv) >= 2:
        bars = int(sys.argv[1])

    if bars < 1:
        raise ValueError("bars 至少需為 1")

    ok, message = test_connection()
    if not ok:
        raise RuntimeError(message)

    settings = load_settings()
    client = BinanceClient(settings)

    with connection_scope() as conn:
        active_strategy = load_active_strategy(conn)

    params = active_strategy["params_json"]
    entry_threshold = float(params.get("entry_threshold", 0.0))
    exit_threshold = float(params.get("exit_threshold", 0.0))
    reverse_threshold = float(params.get("reverse_threshold", 0.0))
    reverse_gap = float(params.get("reverse_gap", 0.0))

    need_klines = 60 + bars - 1
    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=need_klines,
    )

    rows: list[dict[str, Any]] = []

    for idx in range(59, len(klines)):
        window = klines[idx - 59: idx + 1]
        row = _build_row(
            klines_window=window,
            current_position_side=None,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            reverse_threshold=reverse_threshold,
            reverse_gap=reverse_gap,
        )
        rows.append(row)

    print("\n==============================")
    print(" inspect_strategy_scores 結果 ")
    print("==============================")
    print(f"symbol = {settings.primary_symbol}")
    print(f"interval = {settings.primary_interval}")
    print(f"bars = {bars}")
    print(f"entry_threshold = {entry_threshold:.6f}")
    print(f"strategy = {active_strategy['version_code']}")
    print("")

    _print_table(rows)

    max_long = max(row["long_score"] for row in rows)
    max_short = max(row["short_score"] for row in rows)
    avg_long = sum(row["long_score"] for row in rows) / len(rows)
    avg_short = sum(row["short_score"] for row in rows) / len(rows)

    print("\n------------------------------")
    print(f"max_long_score  = {max_long:.6f}")
    print(f"max_short_score = {max_short:.6f}")
    print(f"avg_long_score  = {avg_long:.6f}")
    print(f"avg_short_score = {avg_short:.6f}")
    print("------------------------------")


if __name__ == "__main__":
    main()
