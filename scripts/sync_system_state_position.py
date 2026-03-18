"""
Path: scripts/sync_system_state_position.py
說明：同步目前 OPEN 持倉到 system_state，讓 system_state.current_position_id 與 current_position_side 對上 positions。
"""

from __future__ import annotations

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.positions_repo import get_open_position_by_symbol
from storage.repositories.system_state_repo import get_system_state, update_current_position


def main() -> None:
    """
    功能：同步 system_state 與目前 OPEN 持倉。
    """
    setup_logging()
    logger = get_logger("scripts.sync_system_state_position")

    settings = load_settings()

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        open_position = get_open_position_by_symbol(conn, settings.primary_symbol)

        if open_position is None:
            update_current_position(
                conn,
                state_id=1,
                current_position_id=None,
                current_position_side=None,
                updated_by="sync_system_state_position",
            )
            logger.info("目前無 OPEN 持倉，已清空 system_state 持倉欄位")
            return

        update_current_position(
            conn,
            state_id=1,
            current_position_id=int(open_position["position_id"]),
            current_position_side=str(open_position["side"]),
            updated_by="sync_system_state_position",
        )

        logger.info(
            "已同步 system_state 持倉欄位：current_position_id=%s, current_position_side=%s",
            open_position["position_id"],
            open_position["side"],
        )


if __name__ == "__main__":
    main()