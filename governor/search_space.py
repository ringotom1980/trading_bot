"""
Path: governor/search_space.py
說明：search space 讀寫與調整。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_next_search_space(
    current_config: dict[str, Any] | None,
    *,
    family_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    next_config = deepcopy(current_config or {})
    families = dict(next_config.get("families") or {})

    for item in family_actions or []:
        family_key = str(item["family_key"])
        target_weight = float(item["target_weight"])
        families[family_key] = target_weight

    next_config["families"] = families
    return next_config