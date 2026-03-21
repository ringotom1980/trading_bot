"""
Path: scripts/check_guard_state.py
說明：快速檢查 runtime guard 與 entry guard 結果，不送單。
用來驗證 ON / ENTRY_FROZEN / OFF / LIVE 未武裝等狀態。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.guards import evaluate_entry_guard, evaluate_runtime_guard
from storage.db import connection_scope
from storage.repositories.system_state_repo import get_system_state


def _print_json(title: str, data: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    with connection_scope() as conn:
        system_state = get_system_state(conn, state_id=1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

    runtime_allowed, runtime_reason = evaluate_runtime_guard(system_state)
    entry_allowed, entry_reason = evaluate_entry_guard(system_state)

    _print_json("system_state", system_state)
    _print_json(
        "runtime_guard",
        {
            "allowed": runtime_allowed,
            "reason": runtime_reason,
        },
    )
    _print_json(
        "entry_guard",
        {
            "allowed": entry_allowed,
            "reason": entry_reason,
        },
    )


if __name__ == "__main__":
    main()