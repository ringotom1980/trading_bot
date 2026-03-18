"""
Path: scripts/check_order_position_flow.py
說明：測試 order → position → trade 的完整模擬流程，建立開倉委託、開倉持倉、平倉委託、關閉持倉並寫入 trades_log。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.orders_repo import create_order, get_latest_order
from storage.repositories.positions_repo import (
    close_position,
    create_position,
    get_open_position_by_symbol,
    update_position_entry_order_id,
    update_position_exit_order_id,
)
from storage.repositories.system_state_repo import get_system_state, update_current_position
from storage.repositories.trades_repo import create_trade_log, get_latest_trade_log


def main() -> None:
    """
    功能：模擬 order / position / trade 完整資料流。
    """
    setup_logging()
    logger = get_logger("scripts.check_order_position_flow")

    settings = load_settings()

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        existing_open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
        if existing_open_position is not None:
            raise RuntimeError("目前已存在 OPEN 持倉，請先清空後再測試完整流程")

        now_utc = datetime.now(timezone.utc)
        strategy_version_id = int(system_state["active_strategy_version_id"])

        # 1. 建立開倉委託單
        entry_order_id = create_order(
            conn,
            position_id=None,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=str(system_state["trade_mode"]),
            strategy_version_id=strategy_version_id,
            client_order_id="flow_entry_order_001",
            exchange_order_id="flow_exchange_entry_001",
            side="BUY",
            order_type="MARKET",
            reduce_only=False,
            qty=0.01,
            price=None,
            avg_price=70000.0,
            status="FILLED",
            exchange_status_raw="FILLED",
            placed_at=now_utc,
            filled_at=now_utc,
            raw_request={
                "symbol": settings.primary_symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": 0.01,
            },
            raw_response={
                "orderId": "flow_exchange_entry_001",
                "status": "FILLED",
                "avgPrice": "70000.0",
            },
        )
        logger.info("已建立開倉委託單，entry_order_id=%s", entry_order_id)

        # 2. 建立開倉持倉
        position_id = create_position(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=system_state["trade_mode"],
            strategy_version_id=strategy_version_id,
            side="LONG",
            entry_price=70000.0,
            entry_qty=0.01,
            entry_notional=700.0,
            opened_at=now_utc,
            exchange_position_ref=None,
        )
        logger.info("已建立 OPEN 持倉，position_id=%s", position_id)

        # 3. 將 entry_order_id 關聯到 position
        update_position_entry_order_id(
            conn,
            position_id=position_id,
            entry_order_id=entry_order_id,
        )

        # 4. 同步 system_state 持倉欄位
        update_current_position(
            conn,
            state_id=1,
            current_position_id=position_id,
            current_position_side="LONG",
            updated_by="check_order_position_flow_entry",
        )
        logger.info("已同步 system_state 至 OPEN LONG")

        # 5. 建立平倉委託單
        exit_time = now_utc + timedelta(minutes=15)
        exit_order_id = create_order(
            conn,
            position_id=position_id,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=str(system_state["trade_mode"]),
            strategy_version_id=strategy_version_id,
            client_order_id="flow_exit_order_001",
            exchange_order_id="flow_exchange_exit_001",
            side="SELL",
            order_type="MARKET",
            reduce_only=True,
            qty=0.01,
            price=None,
            avg_price=70250.0,
            status="FILLED",
            exchange_status_raw="FILLED",
            placed_at=exit_time,
            filled_at=exit_time,
            raw_request={
                "symbol": settings.primary_symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": 0.01,
                "reduceOnly": True,
            },
            raw_response={
                "orderId": "flow_exchange_exit_001",
                "status": "FILLED",
                "avgPrice": "70250.0",
            },
        )
        logger.info("已建立平倉委託單，exit_order_id=%s", exit_order_id)

        # 6. 關聯 exit_order_id
        update_position_exit_order_id(
            conn,
            position_id=position_id,
            exit_order_id=exit_order_id,
        )

        # 7. 關閉持倉
        entry_price = 70000.0
        exit_price = 70250.0
        qty = 0.01
        gross_pnl = (exit_price - entry_price) * qty
        fees = 2.0
        net_pnl = gross_pnl - fees

        close_position(
            conn,
            position_id=position_id,
            exit_price=exit_price,
            exit_qty=qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            closed_at=exit_time,
            close_reason="MANUAL",
        )
        logger.info("已將持倉更新為 CLOSED")

        # 8. 寫入 trades_log
        trade_id = create_trade_log(
            conn,
            position_id=position_id,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=system_state["trade_mode"],
            strategy_version_id=strategy_version_id,
            side="LONG",
            entry_time=now_utc,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            qty=qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            bars_held=1,
            close_reason="MANUAL",
            entry_order_id=entry_order_id,
            exit_order_id=exit_order_id,
        )
        logger.info("已建立 trades_log，trade_id=%s", trade_id)

        # 9. 清空 system_state 持倉欄位
        update_current_position(
            conn,
            state_id=1,
            current_position_id=None,
            current_position_side=None,
            updated_by="check_order_position_flow_exit",
        )
        logger.info("已清空 system_state 持倉欄位")

        latest_order = get_latest_order(conn)
        latest_trade = get_latest_trade_log(conn)

    logger.info("LATEST_ORDER=%s", latest_order)
    logger.info("LATEST_TRADE=%s", latest_trade)


if __name__ == "__main__":
    main()