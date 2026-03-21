"""
Path: exchange/market_data.py
說明：市場資料存取模組，負責抓取 Binance K 線等公開行情資料，供後續特徵計算與決策流程使用。
本版會過濾掉「尚未收線」的最新 K 棒，避免 runtime 對未完成 bar 重複判斷。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from exchange.binance_client import BinanceClient


def _is_closed_kline(close_time_ms: int) -> bool:
    """
    功能：判斷 K 線是否已收線。
    規則：
        Binance kline close_time 若已小於等於目前 UTC 時間，視為已收線。
    參數：
        close_time_ms: K 線 close_time（毫秒）。
    回傳：
        True 表示已收線；False 表示尚未收線。
    """
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return close_time_ms <= now_ms


def get_latest_klines(
    client: BinanceClient,
    symbol: str,
    interval: str,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """
    功能：取得最新一批「已收線」K 線資料，並轉成較易用的字典格式。
    參數：
        client: Binance API 客戶端。
        symbol: 交易標的，例如 BTCUSDT。
        interval: K 線週期，例如 15m。
        limit: 期望回傳筆數，預設 2。
    回傳：
        已收線 K 線資料字典列表。
    說明：
        為避免最後一根是尚未完成 bar，實際向 Binance 多抓 1 根，
        若最後一根未收線則自動移除。
    """
    fetch_limit = max(limit + 1, 3)

    raw_rows = client.get_public(
        path="/fapi/v1/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": fetch_limit,
        },
    )

    results: list[dict[str, Any]] = []

    for row in raw_rows:
        kline = {
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6]),
            "quote_asset_volume": float(row[7]),
            "trade_count": int(row[8]),
            "taker_buy_base_volume": float(row[9]),
            "taker_buy_quote_volume": float(row[10]),
        }
        results.append(kline)

    if results and not _is_closed_kline(results[-1]["close_time"]):
        results.pop()

    if len(results) < limit:
        raise RuntimeError(
            f"已收線 K 線不足，symbol={symbol}, interval={interval}, need={limit}, got={len(results)}"
        )

    return results[-limit:]