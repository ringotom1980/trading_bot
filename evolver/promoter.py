"""
Path: evolver/promoter.py
說明：自動升版判斷模組，負責依 candidate metrics 與 active metrics 檢查是否通過 promotion gate v3。
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


DEFAULT_WALK_FORWARD_WINDOW_GATE = {
    "min_total_trades": 8,
    "min_profit_factor": 0.90,
    "max_drawdown_relaxation": 8.0,
}


DEFAULT_WALK_FORWARD_GATE = {
    "min_pass_windows": 1,
    "min_beat_active_windows": 1,
    "min_pass_ratio": 0.50,
    "min_avg_net_pnl": 0.0,
    "min_avg_profit_factor": 1.05,
    "max_avg_drawdown": 90.0,
    "max_drawdown_relaxation_vs_active": 3.0,
    "min_profit_factor_edge_vs_active": 0.05,
    "min_net_pnl_edge_vs_active": 0.0,
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
    功能：檢查 candidate 是否通過 promotion gate v3。

    規則：
        1. 先檢查 candidate 自身最低門檻
        2. 若有 active_metrics，再走兩條升版路徑擇一：
           A. 成長型升版：
              - net_pnl >= active_net_pnl + min_net_pnl_improvement
              - profit_factor >= active_profit_factor + min_profit_factor_improvement
              - max_drawdown <= active_max_drawdown + max_drawdown_relaxation

           B. 品質型升版：
              - net_pnl >= active_net_pnl
              - profit_factor >= active_profit_factor + min_profit_factor_improvement
              - max_drawdown <= active_max_drawdown

        3. 只要 A 或 B 任一成立，即視為通過相對 ACTIVE 檢查

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

    # 基本門檻
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

    # 若基本門檻已失敗，直接回傳
    if reasons:
        return False, reasons

    # 相對 ACTIVE 檢查
    if active_metrics:
        active_net_pnl = _to_float(active_metrics, "net_pnl")
        active_profit_factor = _to_float(active_metrics, "profit_factor")
        active_max_drawdown = _to_float(active_metrics, "max_drawdown")

        min_net_pnl_improvement = float(gate_cfg["min_net_pnl_improvement"])
        min_profit_factor_improvement = float(gate_cfg["min_profit_factor_improvement"])
        max_drawdown_relaxation = float(gate_cfg["max_drawdown_relaxation"])

        # 路徑 A：成長型升版
        growth_required_net_pnl = active_net_pnl + min_net_pnl_improvement
        growth_required_profit_factor = active_profit_factor + min_profit_factor_improvement
        growth_allowed_drawdown = active_max_drawdown + max_drawdown_relaxation

        growth_pass = (
            net_pnl >= growth_required_net_pnl
            and profit_factor >= growth_required_profit_factor
            and max_drawdown <= growth_allowed_drawdown
        )

        # 路徑 B：品質型升版
        quality_required_net_pnl = active_net_pnl
        quality_required_profit_factor = active_profit_factor + min_profit_factor_improvement
        quality_allowed_drawdown = active_max_drawdown

        quality_pass = (
            net_pnl >= quality_required_net_pnl
            and profit_factor >= quality_required_profit_factor
            and max_drawdown <= quality_allowed_drawdown
        )

        if not growth_pass and not quality_pass:
            reasons.append(
                "未通過相對 ACTIVE 升版條件："
                "需符合『成長型升版』或『品質型升版』其中之一"
            )

            if net_pnl < growth_required_net_pnl and net_pnl < quality_required_net_pnl:
                reasons.append(
                    f"net_pnl 不足：{net_pnl:.8f} < ACTIVE {active_net_pnl:.8f}"
                )
            elif net_pnl < growth_required_net_pnl:
                reasons.append(
                    f"net_pnl 未達成長型門檻：{net_pnl:.8f} < {growth_required_net_pnl:.8f} "
                    f"(active={active_net_pnl:.8f}, need +{min_net_pnl_improvement:.8f})"
                )

            if profit_factor < growth_required_profit_factor:
                reasons.append(
                    f"profit_factor 改善不足：{profit_factor:.8f} < {growth_required_profit_factor:.8f} "
                    f"(active={active_profit_factor:.8f}, need +{min_profit_factor_improvement:.8f})"
                )

            if max_drawdown > growth_allowed_drawdown and max_drawdown > quality_allowed_drawdown:
                reasons.append(
                    f"max_drawdown 相對 ACTIVE 惡化過多：{max_drawdown:.8f} > {growth_allowed_drawdown:.8f} "
                    f"(active={active_max_drawdown:.8f}, relax={max_drawdown_relaxation:.8f})"
                )
            elif max_drawdown > quality_allowed_drawdown:
                reasons.append(
                    f"max_drawdown 未達品質型門檻：{max_drawdown:.8f} > {quality_allowed_drawdown:.8f} "
                    f"(active={active_max_drawdown:.8f})"
                )

    return len(reasons) == 0, reasons


def check_walk_forward_promotion_gate(
    summary: dict[str, Any],
    gate: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    gate_cfg = dict(DEFAULT_WALK_FORWARD_GATE)
    if gate:
        gate_cfg.update(gate)

    reasons: list[str] = []

    total_windows = int(summary.get("total_windows", 0) or 0)
    pass_windows = int(summary.get("pass_windows", 0) or 0)
    beat_active_windows = int(summary.get("beat_active_windows", 0) or 0)
    pass_ratio = float(summary.get("pass_ratio", 0.0) or 0.0)

    avg_net_pnl = float(summary.get("avg_net_pnl", 0.0) or 0.0)
    avg_profit_factor = float(summary.get("avg_profit_factor", 0.0) or 0.0)
    avg_max_drawdown = float(summary.get("avg_max_drawdown", 0.0) or 0.0)

    active_avg_net_pnl = float(summary.get("active_avg_net_pnl", 0.0) or 0.0)
    active_avg_profit_factor = float(summary.get("active_avg_profit_factor", 0.0) or 0.0)
    active_avg_max_drawdown = float(summary.get("active_avg_max_drawdown", 0.0) or 0.0)

    if total_windows <= 0:
        reasons.append("total_windows 無效：必須大於 0")

    if pass_windows < int(gate_cfg["min_pass_windows"]):
        reasons.append(
            f"pass_windows 未達標：{pass_windows} < {int(gate_cfg['min_pass_windows'])}"
        )

    if beat_active_windows < int(gate_cfg["min_beat_active_windows"]):
        reasons.append(
            f"beat_active_windows 未達標：{beat_active_windows} < {int(gate_cfg['min_beat_active_windows'])}"
        )

    if pass_ratio < float(gate_cfg["min_pass_ratio"]):
        reasons.append(
            f"pass_ratio 未達標：{pass_ratio:.4f} < {float(gate_cfg['min_pass_ratio']):.4f}"
        )

    if avg_net_pnl < float(gate_cfg["min_avg_net_pnl"]):
        reasons.append(
            f"avg_net_pnl 未達標：{avg_net_pnl:.8f} < {float(gate_cfg['min_avg_net_pnl']):.8f}"
        )

    if avg_profit_factor < float(gate_cfg["min_avg_profit_factor"]):
        reasons.append(
            f"avg_profit_factor 未達標：{avg_profit_factor:.8f} < {float(gate_cfg['min_avg_profit_factor']):.8f}"
        )

    if avg_max_drawdown > float(gate_cfg["max_avg_drawdown"]):
        reasons.append(
            f"avg_max_drawdown 超標：{avg_max_drawdown:.8f} > {float(gate_cfg['max_avg_drawdown']):.8f}"
        )

    max_drawdown_relaxation_vs_active = float(gate_cfg["max_drawdown_relaxation_vs_active"])
    min_profit_factor_edge_vs_active = float(gate_cfg["min_profit_factor_edge_vs_active"])
    min_net_pnl_edge_vs_active = float(gate_cfg["min_net_pnl_edge_vs_active"])

    better_net_pnl = avg_net_pnl >= (active_avg_net_pnl + min_net_pnl_edge_vs_active)
    better_profit_factor = avg_profit_factor >= (active_avg_profit_factor + min_profit_factor_edge_vs_active)
    acceptable_drawdown = avg_max_drawdown <= (active_avg_max_drawdown + max_drawdown_relaxation_vs_active)

    if not acceptable_drawdown:
        reasons.append(
            f"avg_max_drawdown 相對 ACTIVE 過大：{avg_max_drawdown:.8f} > "
            f"{(active_avg_max_drawdown + max_drawdown_relaxation_vs_active):.8f}"
        )

    net_pnl_tolerance = 0.5
    profit_factor_tolerance = 0.02

    net_pnl_ok = avg_net_pnl >= (active_avg_net_pnl - net_pnl_tolerance)
    profit_factor_ok = avg_profit_factor >= (active_avg_profit_factor - profit_factor_tolerance)

    if not (net_pnl_ok or better_net_pnl or profit_factor_ok or better_profit_factor):
        reasons.append(
            "walk-forward 相對 ACTIVE 不足：avg_net_pnl 與 avg_profit_factor 皆未達容忍區間"
        )

        if not net_pnl_ok and not better_net_pnl:
            reasons.append(
                f"avg_net_pnl 相對 ACTIVE 偏低：{avg_net_pnl:.8f} < {(active_avg_net_pnl - net_pnl_tolerance):.8f}"
            )

        if not profit_factor_ok and not better_profit_factor:
            reasons.append(
                f"avg_profit_factor 相對 ACTIVE 偏低：{avg_profit_factor:.8f} < {(active_avg_profit_factor - profit_factor_tolerance):.8f}"
            )

    return len(reasons) == 0, reasons


def check_walk_forward_window_gate(
    candidate_metrics: dict[str, Any],
    active_metrics: dict[str, Any],
    gate: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    gate_cfg = dict(DEFAULT_WALK_FORWARD_WINDOW_GATE)
    if gate:
        gate_cfg.update(gate)

    reasons: list[str] = []

    candidate_net_pnl = _to_float(candidate_metrics, "net_pnl")
    candidate_profit_factor = _to_float(candidate_metrics, "profit_factor")
    candidate_max_drawdown = _to_float(candidate_metrics, "max_drawdown")
    candidate_total_trades = _to_int(candidate_metrics, "total_trades")

    active_net_pnl = _to_float(active_metrics, "net_pnl")
    active_profit_factor = _to_float(active_metrics, "profit_factor")
    active_max_drawdown = _to_float(active_metrics, "max_drawdown")

    min_total_trades = int(gate_cfg["min_total_trades"])
    min_profit_factor = float(gate_cfg["min_profit_factor"])
    max_drawdown_relaxation = float(gate_cfg["max_drawdown_relaxation"])

    if candidate_total_trades < min_total_trades:
        reasons.append(
            f"window total_trades 未達標：{candidate_total_trades} < {min_total_trades}"
        )

    path_a_pass = (
        candidate_net_pnl >= active_net_pnl
        and candidate_profit_factor >= min_profit_factor
    )

    path_b_pass = (
        candidate_profit_factor >= active_profit_factor
        and candidate_max_drawdown <= (active_max_drawdown + max_drawdown_relaxation)
    )

    if not path_a_pass and not path_b_pass:
        reasons.append("未通過 walk-forward window gate：需符合 path A 或 path B")

        if candidate_net_pnl < active_net_pnl:
            reasons.append(
                f"window net_pnl 不足：{candidate_net_pnl:.8f} < active {active_net_pnl:.8f}"
            )

        if candidate_profit_factor < min_profit_factor:
            reasons.append(
                f"window profit_factor 未達最低門檻：{candidate_profit_factor:.8f} < {min_profit_factor:.8f}"
            )

        if candidate_profit_factor < active_profit_factor:
            reasons.append(
                f"window profit_factor 未優於 active：{candidate_profit_factor:.8f} < {active_profit_factor:.8f}"
            )

        if candidate_max_drawdown > (active_max_drawdown + max_drawdown_relaxation):
            reasons.append(
                f"window max_drawdown 過大：{candidate_max_drawdown:.8f} > "
                f"{(active_max_drawdown + max_drawdown_relaxation):.8f}"
            )

    return len(reasons) == 0, reasons


def calculate_walk_forward_score(summary: dict[str, Any]) -> float:
    pass_windows = int(summary.get("pass_windows", 0) or 0)
    beat_active_windows = int(summary.get("beat_active_windows", 0) or 0)
    pass_ratio = float(summary.get("pass_ratio", 0.0) or 0.0)

    avg_net_pnl = float(summary.get("avg_net_pnl", 0.0) or 0.0)
    avg_profit_factor = float(summary.get("avg_profit_factor", 0.0) or 0.0)
    avg_max_drawdown = float(summary.get("avg_max_drawdown", 0.0) or 0.0)
    worst_window_drawdown = float(summary.get("worst_window_drawdown", 0.0) or 0.0)

    active_avg_net_pnl = float(summary.get("active_avg_net_pnl", 0.0) or 0.0)
    active_avg_profit_factor = float(summary.get("active_avg_profit_factor", 0.0) or 0.0)
    active_avg_max_drawdown = float(summary.get("active_avg_max_drawdown", 0.0) or 0.0)

    score = 0.0
    score += pass_windows * 8.0
    score += beat_active_windows * 10.0
    score += pass_ratio * 20.0
    score += avg_net_pnl * 1.2
    score += avg_profit_factor * 18.0
    score -= avg_max_drawdown * 0.35
    score -= worst_window_drawdown * 0.15

    score += max(avg_net_pnl - active_avg_net_pnl, 0.0) * 1.5
    score += max(avg_profit_factor - active_avg_profit_factor, 0.0) * 20.0
    score -= max(avg_max_drawdown - active_avg_max_drawdown, 0.0) * 0.8

    return score