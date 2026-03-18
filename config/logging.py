"""
Path: config/logging.py
說明：統一初始化專案 logging，提供 console 輸出格式與後續擴充基礎。
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """
    功能：初始化全域 logging 設定。
    參數：
        level: logging 等級，預設為 INFO。
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """
    功能：取得指定名稱的 logger。
    參數：
        name: logger 名稱。
    回傳：
        logging.Logger 物件。
    """
    return logging.getLogger(name)