"""
Path: scripts/run_weekly_cycle.py
說明：週期流程 v4，依序執行 historical sync、train candidate search/save、
walk-forward validation、rebuild summaries、governor、auto promote。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse
import subprocess
import sys
import json

ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = sys.executable


def _run(cmd: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    print(">>>", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, check=not allow_failure, text=True, capture_output=allow_failure)

    if allow_failure:
        if completed.stdout:
            print(completed.stdout, flush=True)
        if completed.stderr:
            print(completed.stderr, flush=True)

    return completed


def _run_and_capture(cmd: list[str]) -> str:
    print(">>>", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, flush=True)
    if completed.stderr:
        print(completed.stderr, flush=True)
    return completed.stdout


def _looks_like_no_candidates_error(completed: subprocess.CompletedProcess[str]) -> bool:
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    return "找不到可驗證的 top candidates" in output


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
    parser = argparse.ArgumentParser(description="Run weekly cycle v4")
    parser.add_argument("--train-days", type=int, default=30, help="train 區間天數，預設 30")
    parser.add_argument("--validation-days", type=int, default=7, help="validation 區間天數，預設 7")
    parser.add_argument("--search-top", type=int, default=10, help="candidate search 顯示前幾名，預設 10")
    parser.add_argument("--search-max-candidates", type=int, default=80, help="candidate search 最多跑幾組，預設 80")
    parser.add_argument("--search-progress-step", type=int, default=10, help="candidate search 每幾組印一次進度，預設 10")
    parser.add_argument("--search-commit-step", type=int, default=20, help="candidate search/save 每幾組 commit 一次，預設 20")
    parser.add_argument("--validation-top-limit", type=int, default=5, help="validation 驗 top 幾名，預設 5")
    parser.add_argument("--walk-forward-window-days", type=int, default=5, help="walk-forward window 天數，預設 5")
    parser.add_argument("--walk-forward-step-days", type=int, default=3, help="walk-forward step 天數，預設 3")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易標的，預設 BTCUSDT")
    parser.add_argument("--interval", default="15m", help="週期，預設 15m")
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

    print("weekly cycle v4 開始", flush=True)
    print(f"symbol={args.symbol}", flush=True)
    print(f"interval={args.interval}", flush=True)
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
    validation_completed = _run(
        [
            PYTHON_BIN,
            str(ROOT_DIR / "scripts" / "run_walk_forward_validation.py"),
            "--top-limit", str(args.validation_top_limit),
            "--start-date", ranges["validation_start"],
            "--end-date", ranges["validation_end"],
            "--window-days", str(args.walk_forward_window_days),
            "--step-days", str(args.walk_forward_step_days),
            "--persist",
        ],
        allow_failure=True,
    )

    if validation_completed.returncode != 0:
        if _looks_like_no_candidates_error(validation_completed):
            print("walk-forward validation skipped: no top candidates", flush=True)
            print("")
            print("weekly cycle v4 結束（本輪無 candidate 可驗證）", flush=True)
            print(f"symbol={args.symbol}", flush=True)
            print(f"interval={args.interval}", flush=True)
            print(f"train_start={ranges['train_start']}", flush=True)
            print(f"train_end={ranges['train_end']}", flush=True)
            print(f"validation_start={ranges['validation_start']}", flush=True)
            print(f"validation_end={ranges['validation_end']}", flush=True)
            return
        raise subprocess.CalledProcessError(
            validation_completed.returncode,
            validation_completed.args,
            output=validation_completed.stdout,
            stderr=validation_completed.stderr,
        )

    # Step 4: rebuild family performance summary from real candidate + walk-forward data
    family_summary_output = _run_and_capture([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "rebuild_family_performance_summary.py"),
        "--symbol", args.symbol,
        "--interval", args.interval,
    ])
    try:
        family_summary_result = json.loads(family_summary_output)
        print(
            f"family_summary_family_count={family_summary_result.get('family_count')}, "
            f"family_summary_used_candidate_count={family_summary_result.get('used_candidate_count')}",
            flush=True,
        )
    except json.JSONDecodeError:
        print("family summary output is not valid json", flush=True)

    # Step 5: rebuild feature diagnostics summary from real candidate + walk-forward data
    feature_summary_output = _run_and_capture([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "rebuild_feature_diagnostics_summary.py"),
        "--symbol", args.symbol,
        "--interval", args.interval,
    ])
    try:
        feature_summary_result = json.loads(feature_summary_output)
        print(
            f"feature_summary_feature_count={feature_summary_result.get('feature_count')}, "
            f"feature_summary_used_candidate_count={feature_summary_result.get('used_candidate_count')}",
            flush=True,
        )
    except json.JSONDecodeError:
        print("feature summary output is not valid json", flush=True)

    # Step 6: governor analyze + keep/adjust search space
    governor_run_key = f"weekly_governor_{today_utc.strftime('%Y%m%d%H%M%S')}"
    governor_output = _run_and_capture([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "run_governor_cycle.py"),
        "--symbol", args.symbol,
        "--interval", args.interval,
        "--run-key", governor_run_key,
    ])
    try:
        governor_result = json.loads(governor_output)
        print(
            f"governor_status={governor_result.get('status')}, "
            f"governor_run_key={governor_result.get('run_key')}, "
            f"decision_count={len(governor_result.get('decisions', []))}",
            flush=True,
        )
    except json.JSONDecodeError:
        print("governor output is not valid json", flush=True)

    # Step 7: auto promote only walk-forward passed candidate
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
    print("weekly cycle v4 完成", flush=True)
    print(f"symbol={args.symbol}", flush=True)
    print(f"interval={args.interval}", flush=True)
    print(f"train_start={ranges['train_start']}", flush=True)
    print(f"train_end={ranges['train_end']}", flush=True)
    print(f"validation_start={ranges['validation_start']}", flush=True)
    print(f"validation_end={ranges['validation_end']}", flush=True)


if __name__ == "__main__":
    main()