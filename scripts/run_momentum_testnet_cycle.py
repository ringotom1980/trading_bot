"""Dry-run/Testnet cycle for the long-horizon momentum strategy."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.constants import TRADE_MODE_TESTNET, TRADING_STATE_ON  # noqa: E402
from config.settings import Settings, load_settings  # noqa: E402
from exchange.binance_client import BinanceClient  # noqa: E402
from exchange.order_executor import close_position_reduce_only, place_market_order  # noqa: E402
from risk.risk_manager import RiskConfig, calculate_dynamic_position_size  # noqa: E402


SHADOW_STATE_PATH = ROOT_DIR / "logs" / "momentum_shadow_state.json"

SHADOW_STRATEGY_CONFIGS = {
    "long": {
        "lookback_bars": 1920,
        "threshold_pct": 0.03,
        "confirm_bars": 96,
    },
    "mid": {
        "lookback_bars": 96,
        "threshold_pct": 0.008,
        "confirm_bars": 8,
    },
    "short": {
        "lookback_bars": 32,
        "threshold_pct": 0.003,
        "confirm_bars": 4,
    },
}


def _is_closed_kline(close_time_ms: int) -> bool:
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return close_time_ms <= now_ms


def _normalize_kline(row: list[Any]) -> dict[str, Any]:
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
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    end_time: int | None = None

    while len(rows) < limit:
        params: dict[str, Any] = {
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


def _calculate_signal(
    *,
    klines: list[dict[str, Any]],
    lookback_bars: int,
    threshold_pct: float,
    confirm_bars: int,
) -> dict[str, Any]:
    closes = [float(kline["close"]) for kline in klines]
    signals: list[str] = []
    momentums: list[float] = []

    for idx in range(lookback_bars, len(klines)):
        base_close = closes[idx - lookback_bars]
        current_close = closes[idx]
        momentum_pct = 0.0 if base_close == 0 else (current_close - base_close) / base_close
        momentums.append(momentum_pct)
        signals.append(_signal_from_momentum(momentum_pct, threshold_pct))

    current_signal = signals[-1] if signals else "UNKNOWN"
    confirmed = False
    if len(signals) >= confirm_bars:
        confirmed = all(signal == current_signal for signal in signals[-confirm_bars:])

    return {
        "signal": current_signal,
        "confirmed": confirmed,
        "momentum_pct": momentums[-1] if momentums else 0.0,
    }


def _atr_pct(klines: list[dict[str, Any]], window: int = 96) -> float:
    if len(klines) < window + 1:
        return 0.0

    true_ranges: list[float] = []
    for idx in range(len(klines) - window, len(klines)):
        high = float(klines[idx]["high"])
        low = float(klines[idx]["low"])
        prev_close = float(klines[idx - 1]["close"])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    close = float(klines[-1]["close"])
    return 0.0 if close == 0 else sum(true_ranges) / len(true_ranges) / close


def _recent_market_move(
    *,
    klines: list[dict[str, Any]],
    bars: int,
    qty: float = 0.01,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
) -> dict[str, float]:
    if len(klines) < bars + 1:
        return {
            "return_pct": 0.0,
            "long_pnl": 0.0,
            "short_pnl": 0.0,
        }

    entry_price = float(klines[-(bars + 1)]["close"])
    exit_price = float(klines[-1]["close"])
    if entry_price == 0:
        return {
            "return_pct": 0.0,
            "long_pnl": 0.0,
            "short_pnl": 0.0,
        }

    long_entry = entry_price * (1 + slippage_rate)
    long_exit = exit_price * (1 - slippage_rate)
    short_entry = entry_price * (1 - slippage_rate)
    short_exit = exit_price * (1 + slippage_rate)

    long_gross = (long_exit - long_entry) * qty
    short_gross = (short_entry - short_exit) * qty
    long_fees = (long_entry + long_exit) * qty * fee_rate
    short_fees = (short_entry + short_exit) * qty * fee_rate

    return {
        "return_pct": (exit_price - entry_price) / entry_price,
        "long_pnl": long_gross - long_fees,
        "short_pnl": short_gross - short_fees,
    }


def _get_testnet_usdt_balance(client: BinanceClient) -> float:
    balances = client.get_signed("/fapi/v3/balance", timeout=10)
    for item in balances:
        if item.get("asset") == "USDT":
            return float(item.get("availableBalance", item.get("balance", 0)) or 0)
    return 0.0


def _get_testnet_position(client: BinanceClient, symbol: str) -> dict[str, Any]:
    rows = client.get_position_risk(symbol=symbol, timeout=10)
    if isinstance(rows, list) and rows:
        row = rows[0]
    elif isinstance(rows, dict):
        row = rows
    else:
        return {"side": None, "qty": 0.0}

    amount = float(row.get("positionAmt", 0) or 0)
    if amount > 0:
        side = "LONG"
    elif amount < 0:
        side = "SHORT"
    else:
        side = None

    return {
        "side": side,
        "qty": abs(amount),
        "entry_price": float(row.get("entryPrice", 0) or 0),
        "unrealized_pnl": float(row.get("unRealizedProfit", 0) or 0),
        "raw": row,
    }


def _opposite_order_side(position_side: str) -> str:
    if position_side == "LONG":
        return "SELL"
    if position_side == "SHORT":
        return "BUY"
    raise ValueError(f"unknown position_side: {position_side}")


def _entry_order_side(signal: str) -> str:
    if signal == "LONG":
        return "BUY"
    if signal == "SHORT":
        return "SELL"
    raise ValueError(f"unknown signal: {signal}")


def _resolve_action(*, signal: str, confirmed: bool, position_side: str | None) -> str:
    if not confirmed or signal == "FLAT":
        return "HOLD_OR_WAIT"
    if position_side is None:
        return f"ENTER_{signal}"
    if position_side == signal:
        return "HOLD_POSITION"
    return f"REVERSE_{position_side}_TO_{signal}"


def _format_qty(qty: float) -> float:
    return float(f"{qty:.3f}")


def _empty_shadow_state() -> dict[str, Any]:
    return {
        "position": None,
        "realized_pnl": 0.0,
        "trade_count": 0,
        "last_bar_close_time": None,
        "last_action": None,
        "last_updated_at": None,
        "strategies": {},
    }


def _load_shadow_state(path: Path = SHADOW_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return _empty_shadow_state()
    with path.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    state = _empty_shadow_state()
    state.update(loaded)
    if not isinstance(state.get("strategies"), dict):
        state["strategies"] = {}
    return state


def _save_shadow_state(state: dict[str, Any], path: Path = SHADOW_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _shadow_exit_price(*, side: str, price: float, slippage_rate: float) -> float:
    if side == "LONG":
        return price * (1 - slippage_rate)
    if side == "SHORT":
        return price * (1 + slippage_rate)
    raise ValueError(f"unknown side: {side}")


def _shadow_entry_price(*, side: str, price: float, slippage_rate: float) -> float:
    if side == "LONG":
        return price * (1 + slippage_rate)
    if side == "SHORT":
        return price * (1 - slippage_rate)
    raise ValueError(f"unknown side: {side}")


def _shadow_pnl(*, side: str, entry_price: float, exit_price: float, qty: float) -> float:
    if side == "LONG":
        return (exit_price - entry_price) * qty
    if side == "SHORT":
        return (entry_price - exit_price) * qty
    raise ValueError(f"unknown side: {side}")


def _update_shadow_state(
    *,
    state: dict[str, Any],
    signal: str,
    confirmed: bool,
    latest: dict[str, Any],
    qty: float,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    close_time = int(latest["close_time"])
    close_price = float(latest["close"])
    now = datetime.now(tz=timezone.utc).isoformat()
    position = state.get("position")
    action = "SHADOW_HOLD"

    if state.get("last_bar_close_time") == close_time:
        return state

    if position is None:
        if confirmed and signal in {"LONG", "SHORT"} and qty > 0:
            entry_price = _shadow_entry_price(
                side=signal,
                price=close_price,
                slippage_rate=slippage_rate,
            )
            fee = entry_price * qty * fee_rate
            state["position"] = {
                "side": signal,
                "qty": qty,
                "entry_price": entry_price,
                "entry_fee": fee,
                "entry_close_time": close_time,
                "entry_time": now,
            }
            action = f"SHADOW_ENTER_{signal}"
    else:
        position_side = str(position["side"])
        if confirmed and signal != position_side:
            exit_price = _shadow_exit_price(
                side=position_side,
                price=close_price,
                slippage_rate=slippage_rate,
            )
            position_qty = float(position["qty"])
            gross = _shadow_pnl(
                side=position_side,
                entry_price=float(position["entry_price"]),
                exit_price=exit_price,
                qty=position_qty,
            )
            exit_fee = exit_price * position_qty * fee_rate
            net = gross - float(position.get("entry_fee", 0.0)) - exit_fee
            state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + net
            state["trade_count"] = int(state.get("trade_count", 0)) + 1
            state["position"] = None
            action = f"SHADOW_EXIT_{position_side}"

            if signal in {"LONG", "SHORT"} and qty > 0:
                entry_price = _shadow_entry_price(
                    side=signal,
                    price=close_price,
                    slippage_rate=slippage_rate,
                )
                fee = entry_price * qty * fee_rate
                state["position"] = {
                    "side": signal,
                    "qty": qty,
                    "entry_price": entry_price,
                    "entry_fee": fee,
                    "entry_close_time": close_time,
                    "entry_time": now,
                }
                action = f"SHADOW_REVERSE_{position_side}_TO_{signal}"

    state["last_bar_close_time"] = close_time
    state["last_action"] = action
    state["last_updated_at"] = now
    return state


def _shadow_unrealized_pnl(
    *,
    state: dict[str, Any],
    latest_price: float,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
) -> float:
    position = state.get("position")
    if not isinstance(position, dict):
        return 0.0
    side = str(position["side"])
    qty = float(position["qty"])
    exit_price = _shadow_exit_price(
        side=side,
        price=latest_price,
        slippage_rate=slippage_rate,
    )
    gross = _shadow_pnl(
        side=side,
        entry_price=float(position["entry_price"]),
        exit_price=exit_price,
        qty=qty,
    )
    exit_fee = exit_price * qty * fee_rate
    return gross - float(position.get("entry_fee", 0.0)) - exit_fee


def _strategy_state_for(state: dict[str, Any], name: str) -> dict[str, Any]:
    strategies = state.setdefault("strategies", {})
    if not isinstance(strategies, dict):
        strategies = {}
        state["strategies"] = strategies

    current = strategies.get(name)
    if not isinstance(current, dict):
        current = _empty_shadow_state()
        current.pop("strategies", None)
        strategies[name] = current
    return current


def _calculate_multi_timeframe_signals(
    *,
    klines: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, config in SHADOW_STRATEGY_CONFIGS.items():
        result[name] = _calculate_signal(
            klines=klines,
            lookback_bars=int(config["lookback_bars"]),
            threshold_pct=float(config["threshold_pct"]),
            confirm_bars=int(config["confirm_bars"]),
        )
    return result


def _combine_signals(signals: dict[str, dict[str, Any]]) -> str:
    long_signal = signals["long"]
    mid_signal = signals["mid"]
    short_signal = signals["short"]

    if not bool(mid_signal["confirmed"]) or not bool(short_signal["confirmed"]):
        return "WAIT"

    mid_side = str(mid_signal["signal"])
    short_side = str(short_signal["signal"])
    long_side = str(long_signal["signal"])

    if mid_side == short_side and mid_side in {"LONG", "SHORT"}:
        if bool(long_signal["confirmed"]) and long_side not in {mid_side, "FLAT"}:
            return "CONFLICT_WAIT"
        if bool(long_signal["confirmed"]) and long_side == mid_side:
            return f"STRONG_{mid_side}"
        return f"SMALL_{mid_side}"

    return "WAIT"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one momentum Testnet cycle")
    parser.add_argument("--execute-testnet", action="store_true", help="Actually place Binance Testnet orders")
    parser.add_argument("--lookback-bars", type=int, default=1920)
    parser.add_argument("--threshold-pct", type=float, default=0.03)
    parser.add_argument("--confirm-bars", type=int, default=96)
    parser.add_argument("--risk-per-trade-pct", type=float, default=None)
    args = parser.parse_args()

    settings = load_settings()
    market_client = BinanceClient(settings)
    testnet_settings: Settings = replace(settings, trade_mode=TRADE_MODE_TESTNET)
    testnet_client = BinanceClient(testnet_settings)

    required_bars = args.lookback_bars + args.confirm_bars
    klines = _fetch_latest_closed_klines(
        client=market_client,
        symbol=settings.primary_symbol,
        interval=settings.primary_interval,
        limit=required_bars,
    )
    latest = klines[-1]
    recent_2h = _recent_market_move(klines=klines, bars=8)
    recent_24h = _recent_market_move(klines=klines, bars=96)
    signal_result = _calculate_signal(
        klines=klines,
        lookback_bars=args.lookback_bars,
        threshold_pct=args.threshold_pct,
        confirm_bars=args.confirm_bars,
    )
    mtf_signals = _calculate_multi_timeframe_signals(klines=klines)
    combined_signal = _combine_signals(mtf_signals)
    balance = _get_testnet_usdt_balance(testnet_client)
    position = _get_testnet_position(testnet_client, settings.primary_symbol)
    atr_pct = _atr_pct(klines)
    sizing = calculate_dynamic_position_size(
        entry_price=float(latest["close"]),
        atr_pct=atr_pct,
        config=RiskConfig(
            account_equity=balance,
            risk_per_trade_pct=args.risk_per_trade_pct or settings.risk_per_trade_pct,
            leverage=float(settings.default_leverage),
            min_qty=0.001,
            qty_step=0.001,
        ),
    )
    qty = _format_qty(sizing.qty)
    action = _resolve_action(
        signal=str(signal_result["signal"]),
        confirmed=bool(signal_result["confirmed"]),
        position_side=position["side"],
    )
    shadow_state = _load_shadow_state()
    shadow_state = _update_shadow_state(
        state=shadow_state,
        signal=str(signal_result["signal"]),
        confirmed=bool(signal_result["confirmed"]),
        latest=latest,
        qty=qty,
    )
    _save_shadow_state(shadow_state)
    shadow_position = shadow_state.get("position") if isinstance(shadow_state.get("position"), dict) else None
    shadow_unrealized_pnl = _shadow_unrealized_pnl(
        state=shadow_state,
        latest_price=float(latest["close"]),
    )
    shadow_realized_pnl = float(shadow_state.get("realized_pnl", 0.0))
    shadow_total_pnl = shadow_realized_pnl + shadow_unrealized_pnl
    strategy_shadow_summaries: dict[str, dict[str, Any]] = {}
    for name, mtf_signal in mtf_signals.items():
        sub_state = _strategy_state_for(shadow_state, name)
        sub_state = _update_shadow_state(
            state=sub_state,
            signal=str(mtf_signal["signal"]),
            confirmed=bool(mtf_signal["confirmed"]),
            latest=latest,
            qty=qty,
        )
        shadow_state["strategies"][name] = sub_state
        sub_position = sub_state.get("position") if isinstance(sub_state.get("position"), dict) else None
        sub_unrealized = _shadow_unrealized_pnl(
            state=sub_state,
            latest_price=float(latest["close"]),
        )
        sub_realized = float(sub_state.get("realized_pnl", 0.0))
        strategy_shadow_summaries[name] = {
            "position": sub_position,
            "realized_pnl": sub_realized,
            "unrealized_pnl": sub_unrealized,
            "total_pnl": sub_realized + sub_unrealized,
            "trade_count": int(sub_state.get("trade_count", 0)),
            "last_action": sub_state.get("last_action"),
        }
    _save_shadow_state(shadow_state)

    print("momentum testnet cycle")
    print(f"mode={'EXECUTE_TESTNET' if args.execute_testnet else 'DRY_RUN'}")
    print(f"env_trade_mode={settings.trade_mode}")
    print(f"env_trading_state={settings.trading_state}")
    print(f"env_live_armed={settings.live_armed}")
    print(f"symbol={settings.primary_symbol}")
    print(f"interval={settings.primary_interval}")
    print(f"latest_close_time={latest['close_time']}")
    print(f"latest_close={latest['close']}")
    print(f"recent_2h_return_pct={recent_2h['return_pct']:.6f}")
    print(f"recent_2h_long_pnl_001btc={recent_2h['long_pnl']:.8f}")
    print(f"recent_2h_short_pnl_001btc={recent_2h['short_pnl']:.8f}")
    print(f"recent_24h_return_pct={recent_24h['return_pct']:.6f}")
    print(f"recent_24h_long_pnl_001btc={recent_24h['long_pnl']:.8f}")
    print(f"recent_24h_short_pnl_001btc={recent_24h['short_pnl']:.8f}")
    print(f"momentum_pct={float(signal_result['momentum_pct']):.6f}")
    print(f"signal={signal_result['signal']}")
    print(f"confirmed={signal_result['confirmed']}")
    for name in ("long", "mid", "short"):
        mtf_signal = mtf_signals[name]
        print(f"{name}_signal={mtf_signal['signal']}")
        print(f"{name}_confirmed={mtf_signal['confirmed']}")
        print(f"{name}_momentum_pct={float(mtf_signal['momentum_pct']):.6f}")
    print(f"combined_signal={combined_signal}")
    print(f"testnet_usdt_available={balance:.8f}")
    print(f"testnet_position_side={position['side']}")
    print(f"testnet_position_qty={position['qty']}")
    print(f"atr_pct={atr_pct:.6f}")
    print(f"planned_qty={qty:.3f}")
    print(f"planned_notional={sizing.notional:.4f}")
    print(f"planned_risk_usdt={sizing.risk_usdt:.4f}")
    print(f"action={action}")
    print(f"shadow_position_side={None if shadow_position is None else shadow_position.get('side')}")
    print(f"shadow_position_qty={0.0 if shadow_position is None else shadow_position.get('qty')}")
    print(f"shadow_realized_pnl={shadow_realized_pnl:.8f}")
    print(f"shadow_unrealized_pnl={shadow_unrealized_pnl:.8f}")
    print(f"shadow_total_pnl={shadow_total_pnl:.8f}")
    print(f"shadow_trade_count={int(shadow_state.get('trade_count', 0))}")
    print(f"shadow_last_action={shadow_state.get('last_action')}")
    for name in ("long", "mid", "short"):
        summary = strategy_shadow_summaries[name]
        sub_position = summary["position"]
        print(f"{name}_shadow_position_side={None if sub_position is None else sub_position.get('side')}")
        print(f"{name}_shadow_realized_pnl={float(summary['realized_pnl']):.8f}")
        print(f"{name}_shadow_unrealized_pnl={float(summary['unrealized_pnl']):.8f}")
        print(f"{name}_shadow_total_pnl={float(summary['total_pnl']):.8f}")
        print(f"{name}_shadow_trade_count={int(summary['trade_count'])}")
        print(f"{name}_shadow_last_action={summary['last_action']}")

    if not args.execute_testnet:
        print("result=DRY_RUN_NO_ORDER")
        return

    if settings.trade_mode != TRADE_MODE_TESTNET or settings.trading_state != TRADING_STATE_ON:
        raise RuntimeError("execution requires TRADE_MODE=TESTNET and TRADING_STATE=ON")
    if settings.live_armed:
        raise RuntimeError("testnet execution requires LIVE_ARMED=false")
    if qty <= 0:
        raise RuntimeError("planned quantity is zero")

    if action.startswith("REVERSE_") and position["side"] is not None and position["qty"] > 0:
        close_response = close_position_reduce_only(
            testnet_client,
            symbol=settings.primary_symbol,
            side=_opposite_order_side(str(position["side"])),
            quantity=_format_qty(float(position["qty"])),
            new_client_order_id=f"momentum_close_{latest['close_time']}",
        )
        print(f"close_order_id={close_response.get('orderId')}")

    if action.startswith("ENTER_") or action.startswith("REVERSE_"):
        entry_response = place_market_order(
            testnet_client,
            symbol=settings.primary_symbol,
            side=_entry_order_side(str(signal_result["signal"])),
            quantity=qty,
            reduce_only=False,
            new_client_order_id=f"momentum_enter_{signal_result['signal']}_{latest['close_time']}",
        )
        print(f"entry_order_id={entry_response.get('orderId')}")
        print("result=EXECUTED_TESTNET_ORDER")
        return

    print("result=NO_ORDER_ACTION")


if __name__ == "__main__":
    main()
