"""
Path: scripts/check_live_runtime_guard.py
說明：檢查 LIVE 模式下 runtime guard 是否正確阻擋或放行。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.guards import evaluate_runtime_guard
from storage.db import connection_scope
from storage.repositories.system_state_repo import get_system_state


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _print_json(title: str, data: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))


def main() -> None:
    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

    allowed, reason = evaluate_runtime_guard(system_state)

    _print_json("system_state", system_state)
    _print_json(
        "runtime_guard",
        {
            "allowed": allowed,
            "reason": reason,
        },
    )


if __name__ == "__main__":
    main()