"""
Path: governor/analyzer.py
說明：彙整 governor 所需的 family / feature 分析輸入。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as PgConnection

from storage.repositories.family_performance_summary_repo import (
    get_top_family_performance_summaries,
)
from storage.repositories.feature_diagnostics_summary_repo import (
    get_top_feature_diagnostics_summaries,
)


def analyze_governor_inputs(
    conn: PgConnection,
    *,
    symbol: str,
    interval: str,
    family_limit: int = 20,
    feature_limit: int = 20,
) -> dict[str, Any]:
    family_rows = get_top_family_performance_summaries(
        conn,
        symbol=symbol,
        interval=interval,
        limit=family_limit,
    )
    feature_rows = get_top_feature_diagnostics_summaries(
        conn,
        symbol=symbol,
        interval=interval,
        limit=feature_limit,
    )

    return {
        "symbol": symbol,
        "interval": interval,
        "status": "OK",
        "families": family_rows,
        "features": feature_rows,
    }