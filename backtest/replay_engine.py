"""
Path: backtest/replay_engine.py
說明：Backtest v3 重放引擎，依 historical_klines 逐根計算 feature / signal / decision，
並模擬持倉開平倉，支援 cooldown_bars / min_hold_bars / max_bars_hold /
hard_stop_loss_pct / take_profit_pct。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from strategy.decision import calculate_decision
from strategy.features import calculate_feature_pack
from strategy.signals import calculate_signal_scores


def _calc_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    qty: float,
) -> float:
    """
    功能：計算單筆交易 gross pnl。
    """
    if side == "LONG":
        return (exit_price - entry_price) * qty

    if side == "SHORT":
        return (entry_price - exit_price) * qty

    raise ValueError(f"不支援的 side：{side}")


def _to_bar_close_time_value(value: Any) -> int:
    """
    功能：將 close_time 統一轉為毫秒時間戳整數。
    """
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)

    return int(value)


def _calc_return_pct(*, side: str, entry_price: float, current_price: float) -> float:
    """
    功能：計算目前持倉報酬率。
    """
    if entry_price == 0:
        return 0.0

    if side == "LONG":
        return (current_price - entry_price) / entry_price

    if side == "SHORT":
        return (entry_price - current_price) / entry_price

    raise ValueError(f"不支援的 side：{side}")


def _apply_entry_slippage(*, side: str, price: float, slippage_rate: float) -> float:
    """
    功能：模擬進場滑價。
    LONG 進場視為買貴一點；SHORT 進場視為賣低一點。
    """
    if side == "LONG":
        return price * (1 + slippage_rate)
    if side == "SHORT":
        return price * (1 - slippage_rate)
    raise ValueError(f"不支援的 side：{side}")


def _apply_exit_slippage(*, side: str, price: float, slippage_rate: float) -> float:
    """
    功能：模擬出場滑價。
    LONG 出場視為賣差一點；SHORT 出場視為買貴一點。
    """
    if side == "LONG":
        return price * (1 - slippage_rate)
    if side == "SHORT":
        return price * (1 + slippage_rate)
    raise ValueError(f"不支援的 side：{side}")


def _resolve_risk_exit_price(
    *,
    side: str,
    entry_price: float,
    high_price: float,
    low_price: float,
    hard_stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[str | None, float | None]:
    """
    功能：依 bar 的 high / low 判斷風控出場是否觸發，並回傳：
        (reason_code, raw_exit_price)

    規則：
        - 若同一根同時碰到停損與停利，採保守口徑，優先視為停損
        - LONG:
            stop = entry * (1 - stop_loss_pct)
            take = entry * (1 + take_profit_pct)
        - SHORT:
            stop = entry * (1 + stop_loss_pct)
            take = entry * (1 - take_profit_pct)
    """
    stop_loss_hit = False
    take_profit_hit = False
    stop_loss_price: float | None = None
    take_profit_price: float | None = None

    if side == "LONG":
        if hard_stop_loss_pct > 0:
            stop_loss_price = entry_price * (1 - hard_stop_loss_pct)
            stop_loss_hit = low_price <= stop_loss_price
        if take_profit_pct > 0:
            take_profit_price = entry_price * (1 + take_profit_pct)
            take_profit_hit = high_price >= take_profit_price

    elif side == "SHORT":
        if hard_stop_loss_pct > 0:
            stop_loss_price = entry_price * (1 + hard_stop_loss_pct)
            stop_loss_hit = high_price >= stop_loss_price
        if take_profit_pct > 0:
            take_profit_price = entry_price * (1 - take_profit_pct)
            take_profit_hit = low_price <= take_profit_price

    else:
        raise ValueError(f"不支援的 side：{side}")

    if stop_loss_hit:
        return "HARD_STOP_LOSS", stop_loss_price

    if take_profit_hit:
        return "TAKE_PROFIT", take_profit_price

    return None, None


def run_backtest_replay(
    *,
    klines: list[dict[str, Any]],
    strategy_version_id: int,
    symbol: str,
    interval: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    功能：執行 Backtest v3。
    說明：
        - 使用與 runtime 同源的 feature / signal / decision
        - 以 historical_klines 逐根重放
        - 支援 cooldown_bars / min_hold_bars / max_bars_hold
        - 支援 hard_stop_loss_pct / take_profit_pct
    """
    if len(klines) < 61:
        raise ValueError("回測資料不足，至少需要 61 根 K 線")

    qty = float(params.get("qty", 0.01))
    fee_rate = float(params.get("fee_rate", 0.0004))
    slippage_rate = float(params.get("slippage_rate", 0.0005))
    warmup_bars = int(params.get("warmup_bars", 60))
    cooldown_bars = int(params.get("cooldown_bars", 0))
    min_hold_bars = int(params.get("min_hold_bars", 0))
    max_bars_hold = int(params.get("max_bars_hold", 0))
    hard_stop_loss_pct = float(params.get("hard_stop_loss_pct", 0.0))
    take_profit_pct = float(params.get("take_profit_pct", 0.0))

    if warmup_bars < 60:
        warmup_bars = 60

    current_position: dict[str, Any] | None = None
    last_exit_bar_index: int | None = None

    equity = 0.0
    equity_curve: list[float] = []
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for idx in range(warmup_bars - 1, len(klines)):
        window = klines[: idx + 1]
        latest = window[-1]

        feature_pack = calculate_feature_pack(
            symbol=symbol,
            interval=interval,
            klines=window[-60:],
        )

        signal_scores = calculate_signal_scores(feature_pack, params)

        decision_result = calculate_decision(
            long_score=signal_scores["long_score"],
            short_score=signal_scores["short_score"],
            current_position_side=current_position["side"] if current_position else None,
            params=params,
        )

        close_price = float(latest["close"])
        high_price = float(latest["high"])
        low_price = float(latest["low"])
        close_time = latest["close_time"]

        effective_decision = decision_result["decision"]
        effective_reason = decision_result["reason_code"]
        risk_exit_price: float | None = None

        if current_position is None:
            if effective_decision in {"ENTER_LONG", "ENTER_SHORT"} and last_exit_bar_index is not None:
                bars_since_exit = idx - last_exit_bar_index
                if bars_since_exit < cooldown_bars:
                    effective_decision = "WAIT"
                    effective_reason = "COOLDOWN_BLOCKED"

        else:
            bars_held = idx - int(current_position["entry_bar_index"])
            position_side = str(current_position["side"])
            entry_price = float(current_position["entry_price"])

            risk_exit_reason, risk_exit_price = _resolve_risk_exit_price(
                side=position_side,
                entry_price=entry_price,
                high_price=high_price,
                low_price=low_price,
                hard_stop_loss_pct=hard_stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )

            if risk_exit_reason is not None:
                effective_decision = "EXIT"
                effective_reason = risk_exit_reason

            elif max_bars_hold > 0 and bars_held >= max_bars_hold:
                effective_decision = "EXIT"
                effective_reason = "MAX_BARS_HOLD_EXIT"

            elif effective_decision == "EXIT" and bars_held < min_hold_bars:
                effective_decision = "HOLD"
                effective_reason = "MIN_HOLD_BLOCKED"

        decisions.append(
            {
                "bar_close_time": _to_bar_close_time_value(latest["close_time"]),
                "decision": effective_decision,
                "reason_code": effective_reason,
                "long_score": float(signal_scores["long_score"]),
                "short_score": float(signal_scores["short_score"]),
            }
        )

        if current_position is None:
            if effective_decision == "ENTER_LONG":
                entry_price = _apply_entry_slippage(
                    side="LONG",
                    price=close_price,
                    slippage_rate=slippage_rate,
                )
                entry_fee = entry_price * qty * fee_rate
                current_position = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": "LONG",
                    "entry_price": entry_price,
                    "entry_qty": qty,
                    "entry_time": close_time,
                    "entry_bar_index": idx,
                    "entry_fee": entry_fee,
                    "entry_decision": effective_decision,
                }

            elif effective_decision == "ENTER_SHORT":
                entry_price = _apply_entry_slippage(
                    side="SHORT",
                    price=close_price,
                    slippage_rate=slippage_rate,
                )
                entry_fee = entry_price * qty * fee_rate
                current_position = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": "SHORT",
                    "entry_price": entry_price,
                    "entry_qty": qty,
                    "entry_time": close_time,
                    "entry_bar_index": idx,
                    "entry_fee": entry_fee,
                    "entry_decision": effective_decision,
                }

        else:
            if effective_decision == "EXIT":
                raw_exit_price = risk_exit_price if risk_exit_price is not None else close_price
                exit_price = _apply_exit_slippage(
                    side=str(current_position["side"]),
                    price=raw_exit_price,
                    slippage_rate=slippage_rate,
                )
                gross_pnl = _calc_pnl(
                    side=current_position["side"],
                    entry_price=float(current_position["entry_price"]),
                    exit_price=exit_price,
                    qty=qty,
                )
                exit_fee = exit_price * qty * fee_rate
                fees = float(current_position["entry_fee"]) + exit_fee
                net_pnl = gross_pnl - fees
                bars_held = idx - int(current_position["entry_bar_index"])

                trade = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": current_position["side"],
                    "entry_time": current_position["entry_time"],
                    "exit_time": close_time,
                    "entry_price": float(current_position["entry_price"]),
                    "exit_price": exit_price,
                    "exit_trigger_price": raw_exit_price,
                    "exit_bar_close_price": close_price,
                    "qty": qty,
                    "gross_pnl": gross_pnl,
                    "fees": fees,
                    "net_pnl": net_pnl,
                    "bars_held": bars_held,
                    "exit_reason": effective_reason,
                }
                trades.append(trade)

                equity += net_pnl
                equity_curve.append(equity)
                current_position = None
                last_exit_bar_index = idx

    if current_position is not None:
        last_bar = klines[-1]
        final_close_price = float(last_bar["close"])
        final_close_time = last_bar["close_time"]
        final_exit_price = _apply_exit_slippage(
            side=str(current_position["side"]),
            price=final_close_price,
            slippage_rate=slippage_rate,
        )

        gross_pnl = _calc_pnl(
            side=current_position["side"],
            entry_price=float(current_position["entry_price"]),
            exit_price=final_exit_price,
            qty=qty,
        )
        exit_fee = final_exit_price * qty * fee_rate
        fees = float(current_position["entry_fee"]) + exit_fee
        net_pnl = gross_pnl - fees
        bars_held = (len(klines) - 1) - int(current_position["entry_bar_index"])

        trade = {
            "strategy_version_id": strategy_version_id,
            "symbol": symbol,
            "interval": interval,
            "side": current_position["side"],
            "entry_time": current_position["entry_time"],
            "exit_time": final_close_time,
            "entry_price": float(current_position["entry_price"]),
            "exit_price": final_exit_price,
            "exit_trigger_price": final_close_price,
            "exit_bar_close_price": final_close_price,
            "qty": qty,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "bars_held": bars_held,
            "exit_reason": "FORCED_END_OF_BACKTEST",
        }
        trades.append(trade)

        equity += net_pnl
        equity_curve.append(equity)

    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version_id": strategy_version_id,
        "trade_count": len(trades),
        "trades": trades,
        "decisions": decisions,
        "equity_curve": equity_curve,
    }