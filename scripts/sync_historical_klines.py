"""
Path: scripts/sync_historical_klines.py
說明：同步 historical_klines，可指定日期區間；未指定時預設抓最近 2 天。
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


def _utc_day_start(dt: datetime) -> datetime:
    """
    功能：取指定時間所屬 UTC 日期的 00:00:00。
    """
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _parse_date_to_utc_start(date_text: str) -> datetime:
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync historical klines")
    parser.add_argument("--start-date", type=str, default=None, help="UTC start date, format YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None, help="UTC end date, format YYYY-MM-DD")
    args = parser.parse_args()

    settings = load_settings()
    client = BinanceClient(settings)

    if args.start_date and args.end_date:
        start_time = _parse_date_to_utc_start(args.start_date)
        end_time = _parse_date_to_utc_start(args.end_date)
        if start_time >= end_time:
            raise ValueError("--start-date 必須早於 --end-date")
    elif args.start_date or args.end_date:
        raise ValueError("--start-date 與 --end-date 必須一起帶")
    else:
        now_utc = datetime.now(tz=timezone.utc)
        today_utc_start = _utc_day_start(now_utc)

        # 預設抓最近 2 天
        start_time = today_utc_start - timedelta(days=2)
        end_time = today_utc_start

    rows = fetch_klines_range_all(
        client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        start_time=start_time,
        end_time=end_time,
    )

    with connection_scope() as conn:
        written_count = upsert_historical_klines(conn, rows=rows)
        latest_row = get_latest_historical_kline(
            conn,
            symbol=settings.primary_symbol,
            interval=settings.primary_interval,
        )

    print("historical klines sync 完成")
    print(f"symbol={settings.primary_symbol}")
    print(f"interval={settings.primary_interval}")
    print(f"range_start={start_time.isoformat()}")
    print(f"range_end={end_time.isoformat()}")
    print(f"fetched_rows={len(rows)}")
    print(f"written_rows={written_count}")
    if latest_row is not None:
        print(f"latest_open_time={latest_row['open_time'].isoformat()}")
        print(f"latest_close_time={latest_row['close_time'].isoformat()}")
    else:
        print("latest_row=None")


if __name__ == "__main__":
    main()