"""
Path: scripts/check_orders_repo.py
說明：測試 orders repository，建立一筆模擬委託單並查詢最新 order。
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.orders_repo import create_order, get_latest_order
from storage.repositories.system_state_repo import get_system_state


def main() -> None:
    """
    功能：orders repository 測試腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.check_orders_repo")

    settings = load_settings()

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        order_id = create_order(
            conn,
            position_id=None,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=str(system_state["trade_mode"]),
            strategy_version_id=int(system_state["active_strategy_version_id"]),
            client_order_id="sim_order_001",
            exchange_order_id="test_exchange_order_001",
            side="SELL",
            order_type="MARKET",
            reduce_only=False,
            qty=0.01,
            price=None,
            avg_price=72123.4,
            status="FILLED",
            exchange_status_raw="FILLED",
            placed_at=datetime.now(timezone.utc),
            filled_at=datetime.now(timezone.utc),
            raw_request={
                "symbol": settings.primary_symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": 0.01,
            },
            raw_response={
                "orderId": "test_exchange_order_001",
                "status": "FILLED",
                "avgPrice": "72123.4",
            },
        )

        latest_order = get_latest_order(conn)

    logger.info("已建立模擬委託單，order_id=%s", order_id)
    logger.info("LATEST_ORDER=%s", latest_order)


if __name__ == "__main__":
    main()