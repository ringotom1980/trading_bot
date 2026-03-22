"""
Path: evolver/promoter.py
說明：自動升版判斷模組，負責依 candidate metrics 檢查是否通過 promotion gate。
"""

from __future__ import annotations

from typing import Any


DEFAULT_PROMOTION_GATE = {
    "min_net_pnl": 0.0,
    "min_profit_factor": 1.2,
    "max_drawdown": 15.0,
    "min_total_trades": 5,
}


def check_promotion_gate(
    metrics: dict[str, Any],
    gate: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """
    功能：檢查 candidate 是否通過 promotion gate。
    回傳：
        (是否通過, 原因列表)
    """
    gate_cfg = dict(DEFAULT_PROMOTION_GATE)
    if gate:
        gate_cfg.update(gate)

    reasons: list[str] = []

    net_pnl = float(metrics.get("net_pnl", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    total_trades = int(metrics.get("total_trades", 0))

    if net_pnl <= float(gate_cfg["min_net_pnl"]):
        reasons.append(
            f"net_pnl 未達標：{net_pnl:.8f} <= {float(gate_cfg['min_net_pnl']):.8f}"
        )

    if profit_factor < float(gate_cfg["min_profit_factor"]):
        reasons.append(
            f"profit_factor 未達標：{profit_factor:.8f} < {float(gate_cfg['min_profit_factor']):.8f}"
        )

    if max_drawdown > float(gate_cfg["max_drawdown"]):
        reasons.append(
            f"max_drawdown 超標：{max_drawdown:.8f} > {float(gate_cfg['max_drawdown']):.8f}"
        )

    if total_trades < int(gate_cfg["min_total_trades"]):
        reasons.append(
            f"total_trades 未達標：{total_trades} < {int(gate_cfg['min_total_trades'])}"
        )

    return len(reasons) == 0, reasons