"""
Path: governor/search_space.py
說明：search space 讀寫與調整。
"""

from __future__ import annotations

from typing import Any


def build_next_search_space(current_config: dict[str, Any] | None) -> dict[str, Any]:
    return current_config or {}