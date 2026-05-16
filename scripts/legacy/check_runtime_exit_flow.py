"""
Path: scripts/check_runtime_exit_flow.py
說明：測試 runtime 的模擬平倉流程，直接對目前 OPEN 持倉執行 EXIT，驗證 order、position、trades_log 與 system_state 清空流程。
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope
from storage.repositories.decisions_repo import insert_decision_log, mark_decision_executed
from storage.repositories.orders_repo import create_order
from storage.repositories.positions_repo import (
    close_position,
    get_open_position_by_symbol,
    update_position_exit_order_id,
)
from storage.repositories.system_state_repo import get_system_state, update_current_position
from storage.repositories.trades_repo import create_trade_log, get_latest_trade_log


def main() -> None:
    """
    功能：對目前 OPEN 持倉執行一次模擬 EXIT 流程。
    """
    setup_logging()
    logger = get_logger("scripts.check_runtime_exit_flow")

    settings = load_settings()

    with connection_scope() as conn:
        system_state = get_system_state(conn, 1)
        if system_state is None:
            raise RuntimeError("找不到 system_state(id=1)")

        open_position = get_open_position_by_symbol(conn, settings.primary_symbol)
        if open_position is None:
            raise RuntimeError("目前沒有 OPEN 持倉，無法測試 EXIT 流程")

        now_utc = datetime.now(timezone.utc)
        exit_price = float(open_position["entry_price"]) - 150.0 if open_position["side"] == "LONG" else float(open_position["entry_price"]) - 150.0
        qty = float(open_position["entry_qty"])

        decision_id = insert_decision_log(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            bar_open_time=now_utc,
            bar_close_time=now_utc,
            engine_mode=system_state["engine_mode"],
            trade_mode=system_state["trade_mode"],
            strategy_version_id=int(system_state["active_strategy_version_id"]),
            position_id_before=int(open_position["position_id"]),
            position_side_before=str(open_position["side"]),
            decision="EXIT",
            decision_score=0.99,
            reason_code="EXIT_SIGNAL",
            reason_summary="人工測試 EXIT 流程",
            features={"test_mode": True},
            executed=False,
        )

        if open_position["side"] == "LONG":
            order_side = "SELL"
            gross_pnl = (exit_price - float(open_position["entry_price"])) * qty
        else:
            order_side = "BUY"
            gross_pnl = (float(open_position["entry_price"]) - exit_price) * qty

        fees = 2.0
        net_pnl = gross_pnl - fees

        exit_order_id = create_order(
            conn,
            position_id=int(open_position["position_id"]),
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
            engine_mode=system_state["engine_mode"],
            trade_mode=str(system_state["trade_mode"]),
            strategy_version_id=int(system_state["active_strategy_version_id"]),
            client_order_id=f"manual_exit_{int(now_utc.timestamp())}",
            exchange_order_id=f"sim_manual_exit_{int(now_utc.timestamp())}",
            side=order_side,
            order_type="MARKET",
            reduce_only=True,
            qty=qty,
            price=None,
            avg_price=exit_price,
            status="FILLED",
            exchange_status_raw="FILLED",
            placed_at=now_utc,
            filled_at=now_utc,
            raw_request={
                "symbol": settings.primary_symbol,
                "side": order_side,
                "type": "MARKET",
                "quantity": qty,
                "reduceOnly": True,
            },
            raw_response={
                "status": "FILLED",
                "avgPrice": str(exit_price),
            },
        )

        update_position_exit_order_id(
            conn,
            position_id=int(open_position["position_id"]),
            exit_order_id=exit_order_id,
        )

        close_position(
            conn,
            position_id=int(open_position["position_id"]),
            exit_price=exit_price,
            exit_qty=qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            closed_at=now_utc,
            close_reason="SIGNAL_EXIT",
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
            exit_time=now_utc,
            entry_price=float(open_position["entry_price"]),
            exit_price=exit_price,
            qty=qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            bars_held=None,
            close_reason="SIGNAL_EXIT",
            entry_order_id=open_position["entry_order_id"],
            exit_order_id=exit_order_id,
        )

        update_current_position(
            conn,
            state_id=1,
            current_position_id=None,
            current_position_side=None,
            updated_by="check_runtime_exit_flow",
        )

        mark_decision_executed(
            conn,
            decision_id=decision_id,
            executed=True,
            position_id_after=None,
            position_side_after=None,
            linked_order_id=exit_order_id,
        )

        latest_trade = get_latest_trade_log(conn)

    logger.info("已完成 EXIT 測試流程，decision_id=%s, exit_order_id=%s, trade_id=%s", decision_id, exit_order_id, trade_id)
    logger.info("LATEST_TRADE=%s", latest_trade)


if __name__ == "__main__":
    main()