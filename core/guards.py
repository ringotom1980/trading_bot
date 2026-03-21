"""
Path: core/guards.py
說明：交易守門模組，負責依 system_state 判斷是否允許進入交易流程，並回傳清楚原因。
"""

from __future__ import annotations

from typing import Any

from core.state_machine import (
    calculate_held_bars,
    has_open_position,
    is_entry_frozen,
    is_live_armed,
    is_live_mode,
    is_realtime_mode,
    is_trading_off,
    is_trading_on,
)


def evaluate_runtime_guard(system_state: dict[str, Any]) -> tuple[bool, str]:
    """
    功能：判斷 runtime 是否允許進入即時交易流程。
    參數：
        system_state: system_state 資料字典。
    回傳：
        (是否允許, 原因說明)
    """
    if not is_realtime_mode(system_state):
        return False, "目前 engine_mode 不是 REALTIME，略過即時交易流程"

    if is_trading_off(system_state):
        return False, "目前 trading_state=OFF，暫不進入交易流程"

    if is_entry_frozen(system_state):
        if has_open_position(system_state):
            return True, "目前 trading_state=ENTRY_FROZEN，禁止新倉，但允許持倉管理流程"
        return False, "目前 trading_state=ENTRY_FROZEN，且無持倉，暫不進入交易流程"

    if is_live_mode(system_state) and not bool(system_state["live_armed"]):
        return False, "目前 trade_mode=LIVE，但 live_armed=false，禁止進入真實交易流程"

    if is_trading_on(system_state):
        return True, "目前狀態允許進入交易流程"

    return False, "目前狀態未通過交易守門條件"


def evaluate_entry_guard(system_state: dict[str, Any]) -> tuple[bool, str]:
    """
    功能：判斷目前是否允許新開倉。
    參數：
        system_state: system_state 資料字典。
    回傳：
        (是否允許, 原因說明)
    """
    if not is_realtime_mode(system_state):
        return False, "engine_mode 不是 REALTIME，禁止新倉"

    if is_trading_off(system_state):
        return False, "trading_state=OFF，禁止新倉"

    if is_entry_frozen(system_state):
        return False, "trading_state=ENTRY_FROZEN，禁止新倉"

    if has_open_position(system_state):
        return False, "目前已有 OPEN 持倉，禁止重複新倉"

    if is_live_mode(system_state) and not is_live_armed(system_state):
        return False, "trade_mode=LIVE 但未武裝，禁止新倉"

    if not is_trading_on(system_state):
        return False, "trading_state 不是 ON，禁止新倉"

    return True, "允許新倉"


def evaluate_exit_guard(
    system_state: dict[str, Any],
    *,
    open_position: dict[str, Any] | None,
    current_bar_close_time,
    min_hold_bars: int,
) -> tuple[bool, str]:
    """
    功能：判斷目前是否允許平倉。
    參數：
        system_state: system_state 資料字典。
        open_position: 目前 OPEN 持倉資料。
        current_bar_close_time: 當前 bar close time。
        min_hold_bars: 最小持有 bar 數。
    回傳：
        (是否允許, 原因說明)
    """
    if not is_realtime_mode(system_state):
        return False, "engine_mode 不是 REALTIME，禁止平倉流程"

    if open_position is None:
        return False, "目前沒有 OPEN 持倉，無需平倉"

    held_bars = calculate_held_bars(
        opened_at=open_position["opened_at"],
        current_bar_close_time=current_bar_close_time,
        bar_minutes=15,
    )

    if held_bars < min_hold_bars:
        return False, f"尚未達到 min_hold_bars={min_hold_bars}，目前僅持有 {held_bars} 根"

    if is_live_mode(system_state) and not is_live_armed(system_state):
        return False, "trade_mode=LIVE 但未武裝，禁止平倉流程"

    if is_trading_off(system_state):
        return False, "trading_state=OFF，禁止平倉"

    return True, "允許平倉"