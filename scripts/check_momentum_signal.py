"""Read-only current signal check for the long-horizon momentum strategy."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import load_settings  # noqa: E402
from exchange.binance_client import BinanceClient  # noqa: E402


def _is_closed_kline(close_time_ms: int) -> bool:
    from datetime import datetime, timezone

    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return close_time_ms <= now_ms


def _normalize_kline(row: list) -> dict:
    return {
        "open_time": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "close_time": int(row[6]),
    }


def _fetch_latest_closed_klines(
    *,
    client: BinanceClient,
    symbol: str,
    interval: str,
    limit: int,
) -> list[dict]:
    rows: list[dict] = []
    end_time: int | None = None

    while len(rows) < limit:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(1500, limit - len(rows) + 2),
        }
        if end_time is not None:
            params["endTime"] = end_time

        raw_rows = client.get_public(path="/fapi/v1/klines", params=params)
        if not raw_rows:
            break

        batch = [_normalize_kline(row) for row in raw_rows]
        batch = [row for row in batch if _is_closed_kline(int(row["close_time"]))]
        rows = batch + rows
        end_time = int(raw_rows[0][0]) - 1

        if len(raw_rows) < int(params["limit"]):
            break

    deduped = {int(row["open_time"]): row for row in rows}
    ordered = [deduped[key] for key in sorted(deduped)]
    if len(ordered) < limit:
        raise RuntimeError(f"not enough closed klines: need={limit}, got={len(ordered)}")
    return ordered[-limit:]


def _signal_from_momentum(momentum_pct: float, threshold_pct: float) -> str:
    if momentum_pct >= threshold_pct:
        return "LONG"
    if momentum_pct <= -threshold_pct:
        return "SHORT"
    return "FLAT"


def main() -> None:
    settings = load_settings()
    lookback_bars = 1920
    threshold_pct = 0.03
    confirm_bars = 96
    required_bars = lookback_bars + confirm_bars

    client = BinanceClient(settings)
    klines = _fetch_latest_closed_klines(
        client=client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=required_bars,
    )
    closes = [float(kline["close"]) for kline in klines]

    signals: list[str] = []
    momentums: list[float] = []
    for idx in range(lookback_bars, len(klines)):
        base_close = closes[idx - lookback_bars]
        current_close = closes[idx]
        momentum_pct = 0.0 if base_close == 0 else (current_close - base_close) / base_close
        momentums.append(momentum_pct)
        signals.append(_signal_from_momentum(momentum_pct, threshold_pct))

    confirmed = False
    current_signal = signals[-1] if signals else "UNKNOWN"
    if len(signals) >= confirm_bars:
        confirmed = all(signal == current_signal for signal in signals[-confirm_bars:])

    latest = klines[-1]
    latest_momentum = momentums[-1] if momentums else 0.0

    print("momentum signal check")
    print(f"symbol={settings.primary_symbol}")
    print(f"interval={settings.primary_interval}")
    print(f"trade_mode={settings.trade_mode}")
    print(f"trading_state={settings.trading_state}")
    print(f"live_armed={settings.live_armed}")
    print(f"lookback_bars={lookback_bars}")
    print(f"threshold_pct={threshold_pct}")
    print(f"confirm_bars={confirm_bars}")
    print(f"latest_close_time={latest['close_time']}")
    print(f"latest_close={latest['close']}")
    print(f"momentum_pct={latest_momentum:.6f}")
    print(f"signal={current_signal}")
    print(f"confirmed={confirmed}")
    print("action=READ_ONLY_NO_ORDER")


if __name__ == "__main__":
    main()
