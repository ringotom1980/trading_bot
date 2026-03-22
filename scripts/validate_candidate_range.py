"""
Path: scripts/validate_candidate_range.py
說明：用指定 candidate_id 或 top candidates 的 params，在 validation 區間做驗證回測，並可寫回 candidate 狀態。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.metrics import calculate_backtest_metrics
from backtest.replay_engine import run_backtest_replay
from evolver.promoter import check_promotion_gate
from storage.db import connection_scope
from storage.repositories.historical_klines_repo import get_historical_klines_by_range
from storage.repositories.strategy_candidates_repo import (
    get_strategy_candidate_by_id,
    get_top_strategy_candidates,
    update_strategy_candidate_validation_result,
)
from storage.repositories.strategy_versions_repo import (
    get_active_strategy_version,
    get_strategy_version_by_code,
)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


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


def _build_active_validation_metrics(
    *,
    conn,
    active_strategy: dict[str, Any],
    start_time: datetime,
    end_time: datetime,
) -> tuple[dict[str, Any], int]:
    klines = get_historical_klines_by_range(
        conn,
        symbol=str(active_strategy["symbol"]),
        interval=str(active_strategy["interval"]),
        start_time=start_time,
        end_time=end_time,
    )

    if len(klines) < 61:
        raise RuntimeError(f"ACTIVE 驗證區間歷史 K 線不足，got={len(klines)}")

    active_params = dict(active_strategy["params_json"] or {})
    active_metrics = _run_strategy_validation(
        klines=klines,
        strategy_version_id=int(active_strategy["strategy_version_id"]),
        symbol=str(active_strategy["symbol"]),
        interval=str(active_strategy["interval"]),
        params=active_params,
    )
    return active_metrics, len(klines)


def _validate_one_candidate(
    *,
    conn,
    candidate: dict[str, Any],
    start_time: datetime,
    end_time: datetime,
    active_validation_metrics: dict[str, Any],
    persist_result: bool,
) -> dict[str, Any]:
    klines = get_historical_klines_by_range(
        conn,
        symbol=str(candidate["symbol"]),
        interval=str(candidate["interval"]),
        start_time=start_time,
        end_time=end_time,
    )

    if len(klines) < 61:
        raise RuntimeError(
            f"歷史 K 線不足，candidate_id={candidate['candidate_id']} got={len(klines)}"
        )

    params = dict(candidate["params_json"] or {})

    candidate_metrics = _run_strategy_validation(
        klines=klines,
        strategy_version_id=int(candidate["source_strategy_version_id"]),
        symbol=str(candidate["symbol"]),
        interval=str(candidate["interval"]),
        params=params,
    )

    passed, reasons = check_promotion_gate(
        candidate_metrics=candidate_metrics,
        active_metrics=active_validation_metrics,
        candidate_rank_score=float(candidate["rank_score"]),
    )

    validation_status = "VALIDATED_PASS" if passed else "VALIDATED_FAIL"

    validation_payload = {
        "validation_range_start": start_time.isoformat(),
        "validation_range_end": end_time.isoformat(),
        "validation_status": validation_status,
        "candidate_id": int(candidate["candidate_id"]),
        "candidate_no": int(candidate["candidate_no"]),
        "candidate_rank_score": float(candidate["rank_score"]),
        "candidate_validation_metrics": candidate_metrics,
        "active_validation_metrics": active_validation_metrics,
        "validation_reasons": reasons,
    }

    if persist_result:
        update_strategy_candidate_validation_result(
            conn,
            candidate_id=int(candidate["candidate_id"]),
            validation_status=validation_status,
            validation_payload=validation_payload,
        )

    return {
        "candidate_id": int(candidate["candidate_id"]),
        "candidate_no": int(candidate["candidate_no"]),
        "symbol": str(candidate["symbol"]),
        "interval": str(candidate["interval"]),
        "rank_score": float(candidate["rank_score"]),
        "validation_status": validation_status,
        "validation_metrics": candidate_metrics,
        "validation_reasons": reasons,
        "kline_count": len(klines),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate candidate on validation range")
    parser.add_argument("--candidate-id", type=int, default=None, help="驗證單一 candidate")
    parser.add_argument("--top-limit", type=int, default=None, help="驗證 top N candidates")
    parser.add_argument("--start-date", type=str, required=True, help="validation start YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="validation end YYYY-MM-DD")
    parser.add_argument("--version-code", type=str, default=None, help="不帶則使用 ACTIVE")
    parser.add_argument("--persist", action="store_true", help="是否將 validation 結果寫回 DB")
    args = parser.parse_args()

    if args.candidate_id is None and args.top_limit is None:
        raise ValueError("至少要帶 --candidate-id 或 --top-limit 其中一個")

    if args.candidate_id is not None and args.top_limit is not None:
        raise ValueError("--candidate-id 與 --top-limit 只能擇一使用")

    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    if start_time >= end_time:
        raise ValueError("start-date 必須早於 end-date")

    with connection_scope() as conn:
        if args.version_code:
            active_strategy = get_strategy_version_by_code(conn, args.version_code)
            if active_strategy is None:
                raise RuntimeError(f"找不到策略版本：{args.version_code}")
        else:
            active_strategy = get_active_strategy_version(conn)
            if active_strategy is None:
                raise RuntimeError("找不到 ACTIVE 策略版本")

        active_validation_metrics, active_kline_count = _build_active_validation_metrics(
            conn=conn,
            active_strategy=active_strategy,
            start_time=start_time,
            end_time=end_time,
        )

        candidates: list[dict[str, Any]] = []

        if args.candidate_id is not None:
            candidate = get_strategy_candidate_by_id(conn, candidate_id=args.candidate_id)
            if candidate is None:
                raise RuntimeError(f"找不到 candidate_id={args.candidate_id}")
            candidates = [candidate]
        else:
            candidates = get_top_strategy_candidates(
                conn,
                source_strategy_version_id=int(active_strategy["strategy_version_id"]),
                symbol=str(active_strategy["symbol"]),
                interval=str(active_strategy["interval"]),
                tested_range_start=start_time,
                tested_range_end=end_time,
                limit=int(args.top_limit or 10),
                ignore_range=True,
            )
            if not candidates:
                raise RuntimeError("找不到可驗證的 top candidates")

        results: list[dict[str, Any]] = []

        for candidate in candidates:
            result = _validate_one_candidate(
                conn=conn,
                candidate=candidate,
                start_time=start_time,
                end_time=end_time,
                active_validation_metrics=active_validation_metrics,
                persist_result=bool(args.persist),
            )
            results.append(result)

    print("candidate validation 完成")
    print(f"validation_range_start={start_time.isoformat()}")
    print(f"validation_range_end={end_time.isoformat()}")
    print(f"validated_count={len(results)}")
    print("")
    print("===== ACTIVE VALIDATION BASELINE =====")
    print(f"symbol={active_strategy['symbol']}")
    print(f"interval={active_strategy['interval']}")
    print(f"kline_count={active_kline_count}")
    print(f"total_trades={int(active_validation_metrics['total_trades'])}")
    print(f"win_rate={float(active_validation_metrics['win_rate']):.4f}")
    print(f"net_pnl={float(active_validation_metrics['net_pnl']):.8f}")
    print(f"profit_factor={float(active_validation_metrics['profit_factor']):.8f}")
    print(f"max_drawdown={float(active_validation_metrics['max_drawdown']):.8f}")
    print("active_validation_metrics=" + json.dumps(active_validation_metrics, ensure_ascii=False, sort_keys=True))
    print("")

    for idx, result in enumerate(results, start=1):
        metrics = result["validation_metrics"]
        reasons = result["validation_reasons"]

        print(f"===== VALIDATION {idx} =====")
        print(f"candidate_id={result['candidate_id']}")
        print(f"candidate_no={result['candidate_no']}")
        print(f"symbol={result['symbol']}")
        print(f"interval={result['interval']}")
        print(f"rank_score={result['rank_score']:.8f}")
        print(f"validation_status={result['validation_status']}")
        print(f"kline_count={result['kline_count']}")
        print(f"total_trades={int(metrics['total_trades'])}")
        print(f"win_rate={float(metrics['win_rate']):.4f}")
        print(f"net_pnl={float(metrics['net_pnl']):.8f}")
        print(f"profit_factor={float(metrics['profit_factor']):.8f}")
        print(f"max_drawdown={float(metrics['max_drawdown']):.8f}")
        print("validation_metrics=" + json.dumps(metrics, ensure_ascii=False, sort_keys=True))
        if reasons:
            print("validation_reasons=" + json.dumps(reasons, ensure_ascii=False))
        print("")


if __name__ == "__main__":
    main()