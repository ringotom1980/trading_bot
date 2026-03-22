"""
Path: backtest/replay_engine.py
說明：Backtest v1 重放引擎，依 historical_klines 逐根計算 feature / signal / decision，並模擬持倉開平倉。
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


def run_backtest_replay(
    *,
    klines: list[dict[str, Any]],
    strategy_version_id: int,
    symbol: str,
    interval: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    功能：執行 Backtest v1。
    說明：
        - 使用與 runtime 同源的 feature / signal / decision
        - 以 historical_klines 逐根重放
        - 第一版先用固定 qty 與簡化 fee 模型
    """
    if len(klines) < 61:
        raise ValueError("回測資料不足，至少需要 61 根 K 線")

    qty = float(params.get("qty", 0.01))
    fee_rate = float(params.get("fee_rate", 0.0004))
    warmup_bars = int(params.get("warmup_bars", 60))

    if warmup_bars < 60:
        warmup_bars = 60

    current_position: dict[str, Any] | None = None
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

        decisions.append(
            {
                "bar_close_time": _to_bar_close_time_value(latest["close_time"]),
                "decision": decision_result["decision"],
                "long_score": float(signal_scores["long_score"]),
                "short_score": float(signal_scores["short_score"]),
            }
        )

        close_price = float(latest["close"])
        close_time = latest["close_time"]

        if current_position is None:
            if decision_result["decision"] == "ENTER_LONG":
                entry_fee = close_price * qty * fee_rate
                current_position = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": "LONG",
                    "entry_price": close_price,
                    "entry_qty": qty,
                    "entry_time": close_time,
                    "entry_bar_index": idx,
                    "entry_fee": entry_fee,
                    "entry_decision": decision_result["decision"],
                }

            elif decision_result["decision"] == "ENTER_SHORT":
                entry_fee = close_price * qty * fee_rate
                current_position = {
                    "strategy_version_id": strategy_version_id,
                    "symbol": symbol,
                    "interval": interval,
                    "side": "SHORT",
                    "entry_price": close_price,
                    "entry_qty": qty,
                    "entry_time": close_time,
                    "entry_bar_index": idx,
                    "entry_fee": entry_fee,
                    "entry_decision": decision_result["decision"],
                }

        else:
            if decision_result["decision"] == "EXIT":
                gross_pnl = _calc_pnl(
                    side=current_position["side"],
                    entry_price=float(current_position["entry_price"]),
                    exit_price=close_price,
                    qty=qty,
                )
                exit_fee = close_price * qty * fee_rate
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
                    "exit_price": close_price,
                    "qty": qty,
                    "gross_pnl": gross_pnl,
                    "fees": fees,
                    "net_pnl": net_pnl,
                    "bars_held": bars_held,
                }
                trades.append(trade)

                equity += net_pnl
                equity_curve.append(equity)
                current_position = None

    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version_id": strategy_version_id,
        "trade_count": len(trades),
        "trades": trades,
        "decisions": decisions,
        "equity_curve": equity_curve,
    }
