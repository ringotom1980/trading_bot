"""
Path: scripts/run_weekly_cycle.py
說明：週期流程骨架，依序執行 historical sync、candidate search and save、auto promote。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = sys.executable


def _run(cmd: list[str]) -> None:
    print(">>>", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    today_utc = datetime.now(tz=timezone.utc)
    end_date = today_utc.strftime("%Y-%m-%d")
    start_date = (today_utc - timedelta(days=30)).strftime("%Y-%m-%d")

    _run([PYTHON_BIN, str(ROOT_DIR / "scripts" / "sync_historical_klines.py")])

    _run([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "run_candidate_search_and_save.py"),
        "--start-date", start_date,
        "--end-date", end_date,
        "--top", "5",
    ])

    _run([
        PYTHON_BIN,
        str(ROOT_DIR / "scripts" / "auto_promote_best_candidate.py"),
        "--start-date", start_date,
        "--end-date", end_date,
    ])

    print("weekly cycle 完成")


if __name__ == "__main__":
    main()