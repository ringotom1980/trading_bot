"""
Path: core/state_machine.py
說明：系統狀態機模組，負責解讀 system_state，提供 runtime 與後續交易流程使用。
"""

from __future__ import annotations

from typing import Any

from config.constants import (
    ENGINE_MODE_REALTIME,
    TRADE_MODE_LIVE,
    TRADE_MODE_TESTNET,
    TRADING_STATE_ENTRY_FROZEN,
    TRADING_STATE_OFF,
    TRADING_STATE_ON,
)


def is_realtime_mode(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前是否為 REALTIME 模式。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若為 REALTIME 則回傳 True，否則回傳 False。
    """
    return system_state["engine_mode"] == ENGINE_MODE_REALTIME


def is_testnet_mode(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前是否為 TESTNET 模式。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若 trade_mode 為 TESTNET 則回傳 True，否則回傳 False。
    """
    return system_state["trade_mode"] == TRADE_MODE_TESTNET


def is_live_mode(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前是否為 LIVE 模式。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若 trade_mode 為 LIVE 則回傳 True，否則回傳 False。
    """
    return system_state["trade_mode"] == TRADE_MODE_LIVE


def is_trading_on(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前交易狀態是否為 ON。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若 trading_state 為 ON 則回傳 True，否則回傳 False。
    """
    return system_state["trading_state"] == TRADING_STATE_ON


def is_entry_frozen(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前交易狀態是否為 ENTRY_FROZEN。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若 trading_state 為 ENTRY_FROZEN 則回傳 True，否則回傳 False。
    """
    return system_state["trading_state"] == TRADING_STATE_ENTRY_FROZEN


def is_trading_off(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前交易狀態是否為 OFF。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若 trading_state 為 OFF 則回傳 True，否則回傳 False。
    """
    return system_state["trading_state"] == TRADING_STATE_OFF


def has_open_position(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷目前是否存在未平倉持倉。
    參數：
        system_state: system_state 資料字典。
    回傳：
        若 current_position_id 不為空則回傳 True，否則回傳 False。
    """
    return system_state["current_position_id"] is not None


def is_live_armed(system_state: dict[str, Any]) -> bool:
    """
    功能：判斷 LIVE 是否已武裝。
    """
    return bool(system_state["live_armed"])


def calculate_held_bars(
    *,
    opened_at,
    current_bar_close_time,
    bar_minutes: int = 15,
) -> int:
    """
    功能：計算目前持倉已持有幾根 bar。
    規則：
        floor((current_bar_close_time - opened_at) / bar_minutes)
    """
    seconds = (current_bar_close_time - opened_at).total_seconds()
    held_bars = int(seconds // (bar_minutes * 60))
    return max(held_bars, 0)

def summarize_state(system_state: dict[str, Any]) -> str:
    """
    功能：將 system_state 整理成簡短狀態摘要文字。
    參數：
        system_state: system_state 資料字典。
    回傳：
        狀態摘要字串。
    """
    return (
        f"engine_mode={system_state['engine_mode']}, "
        f"trade_mode={system_state['trade_mode']}, "
        f"trading_state={system_state['trading_state']}, "
        f"live_armed={system_state['live_armed']}, "
        f"current_position_id={system_state['current_position_id']}"
    )