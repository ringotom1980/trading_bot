"""
Path: scripts/check_cooldown_guard.py
說明：檢查 cooldown guard 是否依最近一筆已平倉交易正確阻擋或放行新倉。
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

from core.guards import evaluate_cooldown_guard
from services.strategy_service import load_active_strategy
from storage.db import connection_scope
from storage.repositories.trades_repo import get_latest_closed_trade_by_symbol
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

        active_strategy = load_active_strategy(conn)
        latest_closed_trade = get_latest_closed_trade_by_symbol(
            conn,
            symbol=system_state["primary_symbol"],
        )

    cooldown_bars = int(active_strategy["params_json"].get("cooldown_bars", 0))
    current_bar_close_time = system_state["last_bar_close_time"]

    allowed, reason = evaluate_cooldown_guard(
        latest_closed_trade=latest_closed_trade,
        current_bar_close_time=current_bar_close_time,
        cooldown_bars=cooldown_bars,
        bar_minutes=15,
    )

    _print_json("system_state", system_state)
    _print_json("latest_closed_trade", latest_closed_trade)
    _print_json(
        "cooldown_guard",
        {
            "allowed": allowed,
            "reason": reason,
            "cooldown_bars": cooldown_bars,
            "current_bar_close_time": current_bar_close_time,
        },
    )


if __name__ == "__main__":
    main()