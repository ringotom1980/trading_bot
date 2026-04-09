"""
Path: scripts/run_weekly_cycle.py
說明：週期流程 v3，依序執行 historical sync、train candidate search/save、walk-forward validation、auto promote。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = sys.executable


def _run(cmd: list[str]) -> None:
    print(">>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def _resolve_date_ranges(
    *,
    today_utc: datetime,
    train_days: int,
    validation_days: int,
) -> dict[str, str]:
    validation_end = today_utc.strftime("%Y-%m-%d")
    validation_start_dt = today_utc - timedelta(days=validation_days)
    validation_start = validation_start_dt.strftime("%Y-%m-%d")

    train_end_dt = validation_start_dt
    train_start_dt = train_end_dt - timedelta(days=train_days)

    train_start = train_start_dt.strftime("%Y-%m-%d")
    train_end = train_end_dt.strftime("%Y-%m-%d")

    return {
        "train_start": train_start,
        "train_end": train_end,
        "validation_start": validation_start,
        "validation_end": validation_end,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run weekly cycle v3")
    parser.add_argument("--train-days", type=int, default=30, help="train 區間天數，預設 30")
    parser.add_argument("--validation-days", type=int, default=7, help="validation 區間天數，預設 7")
    parser.add_argument("--search-top", type=int, default=10, help="candidate search 顯示前幾名，預設 10")
    parser.add_argument("--search-max-candidates", type=int, default=80, help="candidate search 最多跑幾組，預設 80")
    parser.add_argument("--search-progress-step", type=int, default=10, help="candidate search 每幾組印一次進度，預設 10")
    parser.add_argument("--search-commit-step", type=int, default=20, help="candidate search/save 每幾組 commit 一次，預設 20")
    parser.add_argument("--validation-top-limit", type=int, default=5, help="validation 驗 top 幾名，預設 5")
    parser.add_argument("--walk-forward-window-days", type=int, default=5, help="walk-forward window 天數，預設 5")
    parser.add_argument("--walk-forward-step-days", type=int, default=3, help="walk-forward step 天數，預設 3")
    args = parser.parse_args()

    if args.train_days <= 0:
        raise ValueError("--train-days 必須大於 0")

    if args.validation_days <= 0:
        raise ValueError("--validation-days 必須大於 0")

    if args.search_max_candidates <= 0:
        raise ValueError("--search-max-candidates 必須大於 0")

    if args.validation_top_limit <= 0:
        raise ValueError("--validation-top-limit 必須大於 0")
    
    if args.walk_forward_window_days <= 0:
        raise ValueError("--walk-forward-window-days 必須大於 0")

    if args.walk_forward_step_days <= 0:
        raise ValueError("--walk-forward-step-days 必須大於 0")

    today_utc = datetime.now(tz=timezone.utc)
    ranges = _resolve_date_ranges(
        today_utc=today_utc,
        train_days=args.train_days,
        validation_days=args.validation_days,
    )

    print("weekly cycle v3 開始", flush=True)
    print(f"train_start={ranges['train_start']}", flush=True)
    print(f"train_end={ranges['train_end']}", flush=True)
    print(f"validation_start={ranges['validation_start']}", flush=True)
    print(f"validation_end={ranges['validation_end']}", flush=True)
    print("", flush=True)

    # Step 1: sync historical data for whole train + validation range
    _run([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "sync_historical_klines.py"),
        "--start-date", ranges["train_start"],
        "--end-date", ranges["validation_end"],
    ])

    # Step 2: train range candidate search + save
    _run([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "run_candidate_search_and_save.py"),
        "--start-date", ranges["train_start"],
        "--end-date", ranges["train_end"],
        "--top", str(args.search_top),
        "--max-candidates", str(args.search_max_candidates),
        "--progress-step", str(args.search_progress_step),
        "--commit-step", str(args.search_commit_step),
    ])

    # Step 3: walk-forward validation on same active source strategy top candidates
    _run([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "run_walk_forward_validation.py"),
        "--top-limit", str(args.validation_top_limit),
        "--start-date", ranges["validation_start"],
        "--end-date", ranges["validation_end"],
        "--window-days", str(args.walk_forward_window_days),
        "--step-days", str(args.walk_forward_step_days),
        "--persist",
    ])

    # Step 4: auto promote only walk-forward passed candidate
    _run([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "auto_promote_best_candidate.py"),
        "--start-date", ranges["validation_start"],
        "--end-date", ranges["validation_end"],
        "--top-limit", str(max(args.search_top, args.validation_top_limit)),
        "--window-days", str(args.walk_forward_window_days),
        "--step-days", str(args.walk_forward_step_days),
    ])

    print("")
    print("weekly cycle v3 完成", flush=True)
    print(f"train_start={ranges['train_start']}", flush=True)
    print(f"train_end={ranges['train_end']}", flush=True)
    print(f"validation_start={ranges['validation_start']}", flush=True)
    print(f"validation_end={ranges['validation_end']}", flush=True)


if __name__ == "__main__":
    main()