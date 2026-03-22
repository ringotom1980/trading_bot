"""
Path: scripts/check_features.py
說明：檢查 Feature Pool v1 是否可正常由最新已收線 K 棒計算。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import load_settings
from exchange.binance_client import BinanceClient
from exchange.market_data import get_latest_klines
from strategy.features import calculate_feature_pack


def main() -> None:
    settings = load_settings()
    client = BinanceClient(settings)

    klines = get_latest_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=60,
    )

    feature_pack = calculate_feature_pack(
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        klines=klines,
    )

    print("feature pack 計算成功")
    print(f"symbol={feature_pack['symbol']}")
    print(f"interval={feature_pack['interval']}")
    print(f"bar_close_time={feature_pack['bar_close_time']}")
    print(f"feature_count={len(feature_pack)}")

    for key in sorted(feature_pack.keys()):
        print(f"{key}={feature_pack[key]}")


if __name__ == "__main__":
    main()