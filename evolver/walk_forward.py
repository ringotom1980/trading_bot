"""
Path: evolver/walk_forward.py
說明：Walk-forward 驗證核心邏輯。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backtest.metrics import calculate_backtest_metrics
from backtest.replay_engine import run_backtest_replay
from evolver.promoter import check_promotion_gate, check_walk_forward_promotion_gate
from storage.repositories.historical_klines_repo import get_historical_klines_by_range


def build_walk_forward_windows(
    *,
    validation_start: datetime,
    validation_end: datetime,
    window_days: int,
    step_days: int,
) -> list[dict[str, Any]]:
    if validation_start >= validation_end:
        raise ValueError("validation_start 必須早於 validation_end")

    if window_days <= 0:
        raise ValueError("window_days 必須大於 0")

    if step_days <= 0:
        raise ValueError("step_days 必須大於 0")

    windows: list[dict[str, Any]] = []
    current_start = validation_start
    window_no = 1

    while current_start < validation_end:
        current_end = current_start + timedelta(days=window_days)
        if current_end > validation_end:
            break

        windows.append(
            {
                "window_no": window_no,
                "window_start": current_start,
                "window_end": current_end,
            }
        )
        current_start = current_start + timedelta(days=step_days)
        window_no += 1

    return windows


def _run_strategy_validation(
    *,
    klines: list[dict[str, Any]],
    strategy_version_id: int,
    symbol: str,
    interval: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    replay_result = run_backtest_replay(
        klines=klines,
        strategy_version_id=strategy_version_id,
        symbol=symbol,
        interval=interval,
        params=params,
    )

    return calculate_backtest_metrics(
        trades=replay_result["trades"],
        equity_curve=replay_result["equity_curve"],
    )


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def summarize_walk_forward_results(
    *,
    window_results: list[dict[str, Any]],
) -> dict[str, Any]:
    total_windows = len(window_results)
    pass_windows = sum(1 for item in window_results if bool(item.get("passed", False)))
    beat_active_windows = sum(1 for item in window_results if bool(item.get("beat_active", False)))

    candidate_net_pnls = [float(item["candidate_metrics"].get("net_pnl", 0.0)) for item in window_results]
    candidate_profit_factors = [float(item["candidate_metrics"].get("profit_factor", 0.0)) for item in window_results]
    candidate_drawdowns = [float(item["candidate_metrics"].get("max_drawdown", 0.0)) for item in window_results]

    active_net_pnls = [float(item["active_metrics"].get("net_pnl", 0.0)) for item in window_results]
    active_profit_factors = [float(item["active_metrics"].get("profit_factor", 0.0)) for item in window_results]
    active_drawdowns = [float(item["active_metrics"].get("max_drawdown", 0.0)) for item in window_results]

    summary = {
        "total_windows": total_windows,
        "pass_windows": pass_windows,
        "beat_active_windows": beat_active_windows,
        "pass_ratio": (pass_windows / total_windows) if total_windows > 0 else 0.0,
        "avg_net_pnl": _average(candidate_net_pnls),
        "avg_profit_factor": _average(candidate_profit_factors),
        "avg_max_drawdown": _average(candidate_drawdowns),
        "worst_window_net_pnl": min(candidate_net_pnls) if candidate_net_pnls else 0.0,
        "worst_window_drawdown": max(candidate_drawdowns) if candidate_drawdowns else 0.0,
        "active_avg_net_pnl": _average(active_net_pnls),
        "active_avg_profit_factor": _average(active_profit_factors),
        "active_avg_max_drawdown": _average(active_drawdowns),
    }

    passed, reasons = check_walk_forward_promotion_gate(summary=summary)
    summary["final_status"] = "PASS" if passed else "FAIL"
    summary["final_reasons"] = reasons

    return summary


def run_walk_forward_for_candidate(
    *,
    conn,
    candidate: dict[str, Any],
    active_strategy: dict[str, Any],
    validation_start: datetime,
    validation_end: datetime,
    window_days: int,
    step_days: int,
) -> dict[str, Any]:
    windows = build_walk_forward_windows(
        validation_start=validation_start,
        validation_end=validation_end,
        window_days=window_days,
        step_days=step_days,
    )

    if not windows:
        raise RuntimeError("切不出任何 walk-forward windows，請檢查 validation range / window_days / step_days")

    candidate_params = dict(candidate["params_json"] or {})
    active_params = dict(active_strategy["params_json"] or {})

    window_results: list[dict[str, Any]] = []

    for window in windows:
        window_start = window["window_start"]
        window_end = window["window_end"]

        candidate_klines = get_historical_klines_by_range(
            conn,
            symbol=str(candidate["symbol"]),
            interval=str(candidate["interval"]),
            start_time=window_start,
            end_time=window_end,
        )
        if len(candidate_klines) < 61:
            raise RuntimeError(
                f"walk-forward 歷史 K 線不足，candidate_id={candidate['candidate_id']} "
                f"window_no={window['window_no']} got={len(candidate_klines)}"
            )

        active_klines = get_historical_klines_by_range(
            conn,
            symbol=str(active_strategy["symbol"]),
            interval=str(active_strategy["interval"]),
            start_time=window_start,
            end_time=window_end,
        )
        if len(active_klines) < 61:
            raise RuntimeError(
                f"walk-forward ACTIVE 歷史 K 線不足，window_no={window['window_no']} got={len(active_klines)}"
            )

        candidate_metrics = _run_strategy_validation(
            klines=candidate_klines,
            strategy_version_id=int(candidate["source_strategy_version_id"]),
            symbol=str(candidate["symbol"]),
            interval=str(candidate["interval"]),
            params=candidate_params,
        )

        active_metrics = _run_strategy_validation(
            klines=active_klines,
            strategy_version_id=int(active_strategy["strategy_version_id"]),
            symbol=str(active_strategy["symbol"]),
            interval=str(active_strategy["interval"]),
            params=active_params,
        )

        passed, reasons = check_promotion_gate(
            candidate_metrics=candidate_metrics,
            active_metrics=active_metrics,
            candidate_rank_score=float(candidate["rank_score"]),
        )

        beat_active = (
            float(candidate_metrics.get("net_pnl", 0.0)) >= float(active_metrics.get("net_pnl", 0.0))
            and float(candidate_metrics.get("profit_factor", 0.0)) >= float(active_metrics.get("profit_factor", 0.0))
        )

        window_results.append(
            {
                "window_no": int(window["window_no"]),
                "window_start": window_start,
                "window_end": window_end,
                "candidate_metrics": candidate_metrics,
                "active_metrics": active_metrics,
                "passed": passed,
                "beat_active": beat_active,
                "reasons": reasons,
            }
        )

    summary = summarize_walk_forward_results(window_results=window_results)

    return {
        "candidate_id": int(candidate["candidate_id"]),
        "candidate_no": int(candidate["candidate_no"]),
        "symbol": str(candidate["symbol"]),
        "interval": str(candidate["interval"]),
        "rank_score": float(candidate["rank_score"]),
        "validation_range_start": validation_start,
        "validation_range_end": validation_end,
        "window_days": window_days,
        "step_days": step_days,
        "windows": window_results,
        "summary": summary,
    }