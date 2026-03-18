"""
Path: scripts/check_positions_repo.py
說明：測試 positions repository，建立一筆測試持倉並查詢目前 OPEN 持倉。
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.positions_repo import create_position, get_open_position_by_symbol
from storage.repositories.system_state_repo import get_system_state


def main() -> None:
    """
    功能：positions repository 測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_positions_repo")

    settings = load_settings()

    with connection_scope() as conn:
        existing_open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
        if existing_open_position is not None:
            logger.info("目前已存在 OPEN 持倉，略過建立：%s", existing_open_position)
            return

        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        position_id = create_position(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=system_state["trade_mode"],
            strategy_version_id=int(system_state["active_strategy_version_id"]),
            side="SHORT",
            entry_price=72000.0,
            entry_qty=0.01,
            entry_notional=720.0,
            opened_at=datetime.now(timezone.utc),
            exchange_position_ref=None,
        )

        logger.info("已建立測試持倉，position_id=%s", position_id)

        open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
        logger.info("OPEN_POSITION=%s", open_position)


if __name__ == "__main__":
    main()