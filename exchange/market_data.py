"""
Path: exchange/market_data.py
說明：市場資料存取模組，負責抓取 Binance K 線等公開行情資料，供後續特徵計算與決策流程使用。
"""

from __future__ import annotations

from typing import Any

from exchange.binance_client import BinanceClient


def get_latest_klines(
    client: BinanceClient,
    symbol: str,
    interval: str,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """
    功能：取得最新一批 K 線資料，並轉成較易用的字典格式。
    參數：
        client: Binance API 客戶端。
        symbol: 交易標的，例如 BTCUSDT。
        interval: K 線週期，例如 15m。
        limit: 回傳筆數，預設 2。
    回傳：
        K 線資料字典列表。
    """
    raw_rows = client.get_public(
        path="/fapi/v1/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )

    results: list[dict[str, Any]] = []

    for row in raw_rows:
        results.append(
            {
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
        )

    return results