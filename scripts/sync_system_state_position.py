"""
Path: scripts/sync_system_state_position.py
說明：同步目前 OPEN 持倉到 system_state，讓 system_state.current_position_id 與 current_position_side 對上 positions。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.system_state_repo import get_system_state
from services.reconciliation_service import reconcile_startup_state


def main() -> None:
    """
    功能：以啟動對帳邏輯同步 system_state 與交易所/DB 持倉。
    """
    setup_logging()
    logger = get_logger("scripts.sync_system_state_position")

    settings = load_settings()

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        reconcile_startup_state(
            conn,
            settings=settings,
            system_state=system_state,
        )

        refreshed_state = get_system_state(conn, 1)
        logger.info(
            "同步完成：current_position_id=%s, current_position_side=%s",
            refreshed_state["current_position_id"],
            refreshed_state["current_position_side"],
        )


if __name__ == "__main__":
    main()