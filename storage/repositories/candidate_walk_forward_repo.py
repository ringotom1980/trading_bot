"""
Path: storage/repositories/candidate_walk_forward_repo.py
說明：candidate walk-forward run / window 明細存取層。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def _row_to_walk_forward_run(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "run_id": row[0],
        "candidate_id": row[1],
        "source_strategy_version_id": row[2],
        "symbol": row[3],
        "interval": row[4],
        "train_range_start": row[5],
        "train_range_end": row[6],
        "validation_range_start": row[7],
        "validation_range_end": row[8],
        "window_days": row[9],
        "step_days": row[10],
        "total_windows": row[11],
        "pass_windows": row[12],
        "beat_active_windows": row[13],
        "pass_ratio": float(row[14]),
        "avg_net_pnl": float(row[15]),
        "avg_profit_factor": float(row[16]),
        "avg_max_drawdown": float(row[17]),
        "worst_window_net_pnl": float(row[18]),
        "worst_window_drawdown": float(row[19]),
        "active_avg_net_pnl": float(row[20]),
        "active_avg_profit_factor": float(row[21]),
        "active_avg_max_drawdown": float(row[22]),
        "final_status": row[23],
        "summary_json": row[24],
        "created_at": row[25],
    }


def create_candidate_walk_forward_run(
    conn: PgConnection,
    *,
    candidate_id: int,
    source_strategy_version_id: int,
    symbol: str,
    interval: str,
    train_range_start: datetime | None,
    train_range_end: datetime | None,
    validation_range_start: datetime,
    validation_range_end: datetime,
    window_days: int,
    step_days: int,
    summary: dict[str, Any],
) -> int:
    sql = """
    INSERT INTO candidate_walk_forward_runs (
        candidate_id,
        source_strategy_version_id,
        symbol,
        interval,
        train_range_start,
        train_range_end,
        validation_range_start,
        validation_range_end,
        window_days,
        step_days,
        total_windows,
        pass_windows,
        beat_active_windows,
        pass_ratio,
        avg_net_pnl,
        avg_profit_factor,
        avg_max_drawdown,
        worst_window_net_pnl,
        worst_window_drawdown,
        active_avg_net_pnl,
        active_avg_profit_factor,
        active_avg_max_drawdown,
        final_status,
        summary_json
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
    )
    RETURNING run_id
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                candidate_id,
                source_strategy_version_id,
                symbol,
                interval,
                train_range_start,
                train_range_end,
                validation_range_start,
                validation_range_end,
                window_days,
                step_days,
                int(summary.get("total_windows", 0)),
                int(summary.get("pass_windows", 0)),
                int(summary.get("beat_active_windows", 0)),
                float(summary.get("pass_ratio", 0.0)),
                float(summary.get("avg_net_pnl", 0.0)),
                float(summary.get("avg_profit_factor", 0.0)),
                float(summary.get("avg_max_drawdown", 0.0)),
                float(summary.get("worst_window_net_pnl", 0.0)),
                float(summary.get("worst_window_drawdown", 0.0)),
                float(summary.get("active_avg_net_pnl", 0.0)),
                float(summary.get("active_avg_profit_factor", 0.0)),
                float(summary.get("active_avg_max_drawdown", 0.0)),
                str(summary.get("final_status", "FAIL")),
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("建立 candidate_walk_forward_runs 失敗：未取得 run_id")

    return int(row[0])


def insert_candidate_walk_forward_windows(
    conn: PgConnection,
    *,
    run_id: int,
    windows: list[dict[str, Any]],
) -> int:
    if not windows:
        return 0

    sql = """
    INSERT INTO candidate_walk_forward_windows (
        run_id,
        window_no,
        window_start,
        window_end,
        candidate_metrics_json,
        active_metrics_json,
        candidate_net_pnl,
        candidate_profit_factor,
        candidate_max_drawdown,
        candidate_total_trades,
        active_net_pnl,
        active_profit_factor,
        active_max_drawdown,
        active_total_trades,
        passed,
        beat_active
    )
    VALUES (
        %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """

    params_list: list[tuple[Any, ...]] = []

    for item in windows:
        candidate_metrics = dict(item.get("candidate_metrics") or {})
        active_metrics = dict(item.get("active_metrics") or {})

        params_list.append(
            (
                run_id,
                int(item["window_no"]),
                item["window_start"],
                item["window_end"],
                json.dumps(candidate_metrics, ensure_ascii=False, sort_keys=True),
                json.dumps(active_metrics, ensure_ascii=False, sort_keys=True),
                float(candidate_metrics.get("net_pnl", 0.0)),
                float(candidate_metrics.get("profit_factor", 0.0)),
                float(candidate_metrics.get("max_drawdown", 0.0)),
                int(candidate_metrics.get("total_trades", 0)),
                float(active_metrics.get("net_pnl", 0.0)),
                float(active_metrics.get("profit_factor", 0.0)),
                float(active_metrics.get("max_drawdown", 0.0)),
                int(active_metrics.get("total_trades", 0)),
                bool(item.get("passed", False)),
                bool(item.get("beat_active", False)),
            )
        )

    with conn.cursor() as cursor:
        cursor.executemany(sql, params_list)

    return len(params_list)


def get_latest_candidate_walk_forward_run(
    conn: PgConnection,
    *,
    candidate_id: int,
    validation_range_start: datetime,
    validation_range_end: datetime,
    window_days: int,
    step_days: int,
) -> dict[str, Any] | None:
    sql = """
    SELECT
        run_id,
        candidate_id,
        source_strategy_version_id,
        symbol,
        interval,
        train_range_start,
        train_range_end,
        validation_range_start,
        validation_range_end,
        window_days,
        step_days,
        total_windows,
        pass_windows,
        beat_active_windows,
        pass_ratio,
        avg_net_pnl,
        avg_profit_factor,
        avg_max_drawdown,
        worst_window_net_pnl,
        worst_window_drawdown,
        active_avg_net_pnl,
        active_avg_profit_factor,
        active_avg_max_drawdown,
        final_status,
        summary_json,
        created_at
    FROM candidate_walk_forward_runs
    WHERE candidate_id = %s
      AND validation_range_start = %s
      AND validation_range_end = %s
      AND window_days = %s
      AND step_days = %s
    ORDER BY created_at DESC, run_id DESC
    LIMIT 1
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                candidate_id,
                validation_range_start,
                validation_range_end,
                window_days,
                step_days,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_walk_forward_run(row)