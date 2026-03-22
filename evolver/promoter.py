"""
Path: evolver/promoter.py
說明：自動升版判斷模組，負責依 candidate metrics 與 active metrics 檢查是否通過 promotion gate v2。
"""

from __future__ import annotations

from typing import Any


DEFAULT_PROMOTION_GATE = {
    "min_net_pnl": 0.0,
    "min_profit_factor": 1.05,
    "max_drawdown": 90.0,
    "min_total_trades": 20,
    "min_rank_score": 0.0,
    "min_net_pnl_improvement": 5.0,
    "min_profit_factor_improvement": 0.02,
    "max_drawdown_relaxation": 5.0,
}


def _to_float(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    return float(metrics.get(key, default) or default)


def _to_int(metrics: dict[str, Any], key: str, default: int = 0) -> int:
    return int(metrics.get(key, default) or default)


def check_promotion_gate(
    candidate_metrics: dict[str, Any],
    active_metrics: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
    candidate_rank_score: float | None = None,
) -> tuple[bool, list[str]]:
    """
    功能：檢查 candidate 是否通過 promotion gate v2。
    規則：
        1. 先檢查 candidate 自身最低門檻
        2. 若有 active_metrics，再檢查是否真的優於 ACTIVE
    回傳：
        (是否通過, 原因列表)
    """
    gate_cfg = dict(DEFAULT_PROMOTION_GATE)
    if gate:
        gate_cfg.update(gate)

    reasons: list[str] = []

    net_pnl = _to_float(candidate_metrics, "net_pnl")
    profit_factor = _to_float(candidate_metrics, "profit_factor")
    max_drawdown = _to_float(candidate_metrics, "max_drawdown")
    total_trades = _to_int(candidate_metrics, "total_trades")

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

    if candidate_rank_score is not None and candidate_rank_score < float(gate_cfg["min_rank_score"]):
        reasons.append(
            f"rank_score 未達標：{float(candidate_rank_score):.8f} < {float(gate_cfg['min_rank_score']):.8f}"
        )

    if active_metrics:
        active_net_pnl = _to_float(active_metrics, "net_pnl")
        active_profit_factor = _to_float(active_metrics, "profit_factor")
        active_max_drawdown = _to_float(active_metrics, "max_drawdown")

        required_net_pnl = active_net_pnl + float(gate_cfg["min_net_pnl_improvement"])
        if net_pnl < required_net_pnl:
            reasons.append(
                f"net_pnl 改善不足：{net_pnl:.8f} < {required_net_pnl:.8f} "
                f"(active={active_net_pnl:.8f}, need +{float(gate_cfg['min_net_pnl_improvement']):.8f})"
            )

        required_profit_factor = active_profit_factor + float(gate_cfg["min_profit_factor_improvement"])
        if profit_factor < required_profit_factor:
            reasons.append(
                f"profit_factor 改善不足：{profit_factor:.8f} < {required_profit_factor:.8f} "
                f"(active={active_profit_factor:.8f}, need +{float(gate_cfg['min_profit_factor_improvement']):.8f})"
            )

        allowed_drawdown = active_max_drawdown + float(gate_cfg["max_drawdown_relaxation"])
        if max_drawdown > allowed_drawdown:
            reasons.append(
                f"max_drawdown 相對 ACTIVE 惡化過多：{max_drawdown:.8f} > {allowed_drawdown:.8f} "
                f"(active={active_max_drawdown:.8f}, relax={float(gate_cfg['max_drawdown_relaxation']):.8f})"
            )

    return len(reasons) == 0, reasons