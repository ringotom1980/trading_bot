"""
Path: scripts/check_close_position.py
說明：測試平倉流程，將目前 OPEN 持倉模擬平倉，並寫入 trades_log。
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.positions_repo import close_position, get_open_position_by_symbol
from storage.repositories.trades_repo import create_trade_log, get_latest_trade_log


def main() -> None:
    """
    功能：平倉測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_close_position")

    settings = load_settings()

    with connection_scope() as conn:
        open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
        if open_position is None:
            logger.info("目前沒有 OPEN 持倉，無法進行平倉測試")
            return

        entry_price = float(open_position["entry_price"])
        exit_price = 71800.0
        qty = float(open_position["entry_qty"])
        fees = 2.0

        if open_position["side"] == "LONG":
            gross_pnl = (exit_price - entry_price) * qty
        else:
            gross_pnl = (entry_price - exit_price) * qty

        net_pnl = gross_pnl - fees
        closed_at = datetime.now(timezone.utc)

        close_position(
            conn,
            position_id=int(open_position["position_id"]),
            exit_price=exit_price,
            exit_qty=qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            closed_at=closed_at,
            close_reason="MANUAL",
        )

        trade_id = create_trade_log(
            conn,
            position_id=int(open_position["position_id"]),
            symbol=str(open_position["symbol"]),
            interval=str(open_position["interval"]),
            engine_mode=str(open_position["engine_mode"]),
            trade_mode=open_position["trade_mode"],
            strategy_version_id=int(open_position["strategy_version_id"]),
            side=str(open_position["side"]),
            entry_time=open_position["opened_at"],
            exit_time=closed_at,
            entry_price=entry_price,
            exit_price=exit_price,
            qty=qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            bars_held=None,
            close_reason="MANUAL",
        )

        latest_trade = get_latest_trade_log(conn)

    logger.info("已完成平倉測試，trade_id=%s", trade_id)
    logger.info("LATEST_TRADE=%s", latest_trade)


if __name__ == "__main__":
    main()