"""
Path: scripts/auto_promote_best_candidate.py
說明：自動挑選指定測試區間的最佳 candidate，通過 gate 且無持倉時自動 promote 成 ACTIVE。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evolver.promoter import check_promotion_gate
from storage.db import connection_scope
from storage.repositories.strategy_candidates_repo import (
    get_top_strategy_candidates,
    update_strategy_candidate_status,
)
from storage.repositories.strategy_versions_repo import (
    create_evolved_strategy_version,
    get_active_strategy_version,
    retire_active_strategy,
)
from storage.repositories.system_state_repo import (
    get_system_state,
    update_active_strategy_version,
)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _build_version_code(base_version_code: str, candidate_id: int) -> str:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{base_version_code}_ev_{candidate_id}_{stamp}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto promote best candidate v1")
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--top-limit", type=int, default=10)
    args = parser.parse_args()

    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    if start_time >= end_time:
        raise ValueError("start-date 必須早於 end-date")

    with connection_scope() as conn:
        active_strategy = get_active_strategy_version(conn)
        if active_strategy is None:
            raise RuntimeError("找不到 ACTIVE 策略版本")

        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        if system_state["current_position_id"] is not None:
            print("auto promote 中止：目前仍有持倉，禁止切版")
            return

        top_candidates = get_top_strategy_candidates(
            conn,
            source_strategy_version_id=int(active_strategy["strategy_version_id"]),
            symbol=str(active_strategy["symbol"]),
            interval=str(active_strategy["interval"]),
            tested_range_start=start_time,
            tested_range_end=end_time,
            limit=args.top_limit,
        )

        if not top_candidates:
            print("auto promote 中止：找不到 candidate")
            return

        best_candidate = top_candidates[0]
        metrics = dict(best_candidate["metrics_json"] or {})
        params = dict(best_candidate["params_json"] or {})

        passed, reasons = check_promotion_gate(metrics)

        if not passed:
            update_strategy_candidate_status(
                conn,
                candidate_id=int(best_candidate["candidate_id"]),
                candidate_status="REJECTED",
                note="; ".join(reasons),
            )
            print("auto promote 中止：best candidate 未通過 gate")
            for reason in reasons:
                print(f"- {reason}")
            return

        new_version_code = _build_version_code(
            str(active_strategy["version_code"]),
            int(best_candidate["candidate_id"]),
        )

        retire_active_strategy(
            conn,
            retired_note=f"retired by auto promote from candidate_id={best_candidate['candidate_id']}",
        )

        new_strategy_version_id = create_evolved_strategy_version(
            conn,
            base_version_id=int(active_strategy["strategy_version_id"]),
            version_code=new_version_code,
            symbol=str(active_strategy["symbol"]),
            interval=str(active_strategy["interval"]),
            feature_set=dict(active_strategy["feature_set_json"] or {}),
            params=params,
            backtest_summary=metrics,
            validation_summary={
                "candidate_id": int(best_candidate["candidate_id"]),
                "tested_range_start": start_time.isoformat(),
                "tested_range_end": end_time.isoformat(),
                "gate_passed": True,
            },
            promotion_score=float(best_candidate["rank_score"]),
            note=f"auto promoted from candidate_id={best_candidate['candidate_id']}",
        )

        update_active_strategy_version(
            conn,
            state_id=1,
            active_strategy_version_id=new_strategy_version_id,
            updated_by="auto_promote_best_candidate",
        )

        update_strategy_candidate_status(
            conn,
            candidate_id=int(best_candidate["candidate_id"]),
            candidate_status="APPROVED",
            note=f"auto promoted to strategy_version_id={new_strategy_version_id}",
        )

    print("auto promote 完成")
    print(f"candidate_id={best_candidate['candidate_id']}")
    print(f"new_strategy_version_id={new_strategy_version_id}")
    print(f"new_version_code={new_version_code}")
    print("metrics=" + json.dumps(metrics, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()