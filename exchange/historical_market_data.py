"""
Path: exchange/historical_market_data.py
說明：歷史市場資料抓取模組，負責向 Binance Futures 抓指定區間的 K 線資料，供每日同步與補資料使用。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from exchange.binance_client import BinanceClient

BINANCE_KLINES_MAX_LIMIT = 1500


def _datetime_to_ms(dt: datetime) -> int:
    """
    功能：將 datetime 轉為 UTC 毫秒時間戳。
    """
    if dt.tzinfo is None:
        raise ValueError("datetime 必須帶時區資訊")
    return int(dt.timestamp() * 1000)


def _ms_to_datetime(ms: int) -> datetime:
    """
    功能：將毫秒時間戳轉為 UTC datetime。
    """
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def normalize_kline_row(
    *,
    symbol: str,
    interval: str,
    row: list[Any],
) -> dict[str, Any]:
    """
    功能：將 Binance kline 原始列轉為 historical_klines 可寫入格式。
    """
    return {
        "symbol": symbol,
        "interval": interval,
        "market_type": "FUTURES",
        "source": "BINANCE",
        "open_time": _ms_to_datetime(int(row[0])),
        "close_time": _ms_to_datetime(int(row[6])),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "quote_asset_volume": float(row[7]),
        "trade_count": int(row[8]),
        "taker_buy_base_volume": float(row[9]),
        "taker_buy_quote_volume": float(row[10]),
    }


def fetch_klines_range(
    client: BinanceClient,
    *,
    symbol: str,
    interval: str,
    start_time: datetime,
    end_time: datetime,
    limit: int = BINANCE_KLINES_MAX_LIMIT,
) -> list[dict[str, Any]]:
    """
    功能：抓取指定時間區間的 Binance Futures K 線。
    參數：
        client: Binance API client
        symbol: 交易標的，例如 BTCUSDT
        interval: K 線週期，例如 15m
        start_time: 起始時間（含）
        end_time: 結束時間（不含）
        limit: 每批抓取筆數上限
    回傳：
        正規化後的 K 線列表
    """
    if start_time >= end_time:
        raise ValueError("start_time 必須小於 end_time")

    if limit <= 0 or limit > BINANCE_KLINES_MAX_LIMIT:
        raise ValueError(f"limit 必須介於 1 ~ {BINANCE_KLINES_MAX_LIMIT}")

    raw_rows = client.get_public(
        path="/fapi/v1/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "startTime": _datetime_to_ms(start_time),
            "endTime": _datetime_to_ms(end_time),
            "limit": limit,
        },
    )

    return [
        normalize_kline_row(symbol=symbol, interval=interval, row=row)
        for row in raw_rows
    ]


def fetch_klines_range_all(
    client: BinanceClient,
    *,
    symbol: str,
    interval: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """
    功能：自動分批抓完整時間區間 K 線，直到抓完為止。
    回傳：
        依 open_time 正序排列的完整 K 線列表
    """
    if start_time >= end_time:
        raise ValueError("start_time 必須小於 end_time")

    all_rows: list[dict[str, Any]] = []
    current_start = start_time

    while current_start < end_time:
        batch = fetch_klines_range(
            client,
            symbol=symbol,
            interval=interval,
            start_time=current_start,
            end_time=end_time,
            limit=BINANCE_KLINES_MAX_LIMIT,
        )

        if not batch:
            break

        all_rows.extend(batch)

        last_open_time = batch[-1]["open_time"]
        current_start = last_open_time + timedelta(milliseconds=1)

        if len(batch) < BINANCE_KLINES_MAX_LIMIT:
            break

    deduped: dict[tuple[str, str, datetime], dict[str, Any]] = {}
    for row in all_rows:
        key = (row["symbol"], row["interval"], row["open_time"])
        deduped[key] = row

    results = list(deduped.values())
    results.sort(key=lambda item: item["open_time"])
    return results