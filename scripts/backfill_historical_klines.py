"""
Path: scripts/backfill_historical_klines.py
說明：補歷史 K 線資料，可指定 symbol / interval / start_date / end_date，將 Binance Futures K 線補進 historical_klines。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.historical_market_data import fetch_klines_range_all
from storage.db import connection_scope
from storage.repositories.historical_klines_repo import (
    get_latest_historical_kline,
    upsert_historical_klines,
)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    """
    功能：將 YYYY-MM-DD 轉為 UTC 當日 00:00:00。
    """
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Binance Futures historical klines into historical_klines table."
    )
    parser.add_argument("--symbol", type=str, default=None, help="例如 BTCUSDT")
    parser.add_argument("--interval", type=str, default=None, help="例如 15m")
    parser.add_argument("--start-date", type=str, required=True, help="起始日期，格式 YYYY-MM-DD，含當日")
    parser.add_argument("--end-date", type=str, required=True, help="結束日期，格式 YYYY-MM-DD，不含當日")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=7,
        help="每批抓取天數，預設 7",
    )
    args = parser.parse_args()

    if args.chunk_days <= 0:
        raise ValueError("--chunk-days 必須大於 0")

    settings = load_settings()
    symbol = args.symbol or settings.primary_symbol
    interval = args.interval or settings.primary_interval

    start_time = _parse_date_to_utc_start(args.start_date)
    end_time = _parse_date_to_utc_start(args.end_date)

    if start_time >= end_time:
        raise ValueError("start-date 必須早於 end-date")

    client = BinanceClient(settings)

    total_fetched = 0
    total_written = 0

    current_start = start_time

    while current_start < end_time:
        current_end = min(current_start + timedelta(days=args.chunk_days), end_time)

        rows = fetch_klines_range_all(
            client,
            symbol=symbol,
            interval=interval,
            start_time=current_start,
            end_time=current_end,
        )

        with connection_scope() as conn:
            written_count = upsert_historical_klines(conn, rows=rows)

        total_fetched += len(rows)
        total_written += written_count

        print(
            f"chunk 完成 | symbol={symbol} interval={interval} "
            f"start={current_start.isoformat()} end={current_end.isoformat()} "
            f"fetched_rows={len(rows)} written_rows={written_count}"
        )

        current_start = current_end

    with connection_scope() as conn:
        latest_row = get_latest_historical_kline(
            conn,
            symbol=symbol,
            interval=interval,
        )

    print("historical klines backfill 完成")
    print(f"symbol={symbol}")
    print(f"interval={interval}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"total_fetched_rows={total_fetched}")
    print(f"total_written_rows={total_written}")
    if latest_row is not None:
        print(f"latest_open_time={latest_row['open_time'].isoformat()}")
        print(f"latest_close_time={latest_row['close_time'].isoformat()}")
    else:
        print("latest_row=None")


if __name__ == "__main__":
    main()