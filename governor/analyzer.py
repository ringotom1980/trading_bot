"""
Path: governor/analyzer.py
說明：彙整 candidate / walk-forward / diagnostics 的分析入口。
"""

from __future__ import annotations

from typing import Any


def analyze_governor_inputs(*, symbol: str, interval: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "interval": interval,
        "status": "NOT_IMPLEMENTED",
        "families": [],
        "features": [],
    }