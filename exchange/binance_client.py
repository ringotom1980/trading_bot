"""
Path: exchange/binance_client.py
說明：Binance REST API 基礎客戶端，負責依交易模式切換 Testnet / Live base URL，並提供公共 GET 請求能力。
"""

from __future__ import annotations

from typing import Any

import requests

from config.constants import TRADE_MODE_LIVE, TRADE_MODE_TESTNET
from config.settings import Settings

BINANCE_FUTURES_LIVE_BASE_URL = "https://fapi.binance.com"
BINANCE_FUTURES_TESTNET_BASE_URL = "https://testnet.binancefuture.com"


class BinanceClient:
    """
    功能：Binance REST API 基礎客戶端。
    """

    def __init__(self, settings: Settings) -> None:
        """
        功能：初始化 Binance API 客戶端。
        參數：
            settings: 全域設定物件。
        """
        self.settings = settings
        self.base_url = self._resolve_base_url()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "trading_bot/0.1",
            }
        )

    def _resolve_base_url(self) -> str:
        """
        功能：依目前 trade_mode 決定 Binance API base URL。
        回傳：
            對應模式的 base URL。
        """
        trade_mode = self.settings.trade_mode

        if trade_mode == TRADE_MODE_TESTNET:
            return BINANCE_FUTURES_TESTNET_BASE_URL

        if trade_mode == TRADE_MODE_LIVE:
            return BINANCE_FUTURES_LIVE_BASE_URL

        raise ValueError(f"不支援的 TRADE_MODE：{trade_mode}")

    def build_url(self, path: str) -> str:
        """
        功能：組合完整 API URL。
        參數：
            path: API 路徑，例如 /fapi/v1/klines。
        回傳：
            完整 URL 字串。
        """
        return f"{self.base_url}{path}"

    def get_public(self, path: str, params: dict[str, Any] | None = None, timeout: int = 10) -> Any:
        """
        功能：發送 Binance 公開 GET 請求。
        參數：
            path: API 路徑。
            params: Query string 參數。
            timeout: 逾時秒數。
        回傳：
            API JSON 回應內容。
        """
        url = self.build_url(path)
        response = self.session.get(url, params=params or {}, timeout=timeout)
        response.raise_for_status()
        return response.json()