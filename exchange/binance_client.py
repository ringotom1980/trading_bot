"""
Path: exchange/binance_client.py
說明：Binance REST API 基礎客戶端，負責依交易模式切換 Testnet / Live base URL，並提供公共 GET 與簽名私有請求能力。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import requests

from config.constants import TRADE_MODE_LIVE, TRADE_MODE_TESTNET
from config.settings import Settings

BINANCE_FUTURES_LIVE_BASE_URL = "https://fapi.binance.com"
BINANCE_FUTURES_TESTNET_BASE_URL = "https://demo-fapi.binance.com"


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
        self.api_key = getattr(settings, "binance_api_key", "")
        self.api_secret = getattr(settings, "binance_api_secret", "")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "trading_bot/0.1",
            }
        )

        if self.api_key:
            self.session.headers.update({"X-MBX-APIKEY": self.api_key})

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

    def _build_timestamp(self) -> int:
        """
        功能：產生 Binance 簽名請求用 timestamp。
        """
        return int(time.time() * 1000)

    def _sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        功能：對私有請求參數進行 HMAC SHA256 簽名。
        """
        if not self.api_secret:
            raise ValueError("缺少 BINANCE_API_SECRET，無法發送簽名請求")

        encoded = urlencode(params, doseq=True)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signed_params = dict(params)
        signed_params["signature"] = signature
        return signed_params

    def get_public(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """
        功能：發送 Binance 公開 GET 請求。
        """
        url = self.build_url(path)
        response = self.session.get(url, params=params or {}, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def send_signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """
        功能：發送 Binance 私有簽名請求。
        參數：
            method: HTTP 方法，支援 GET / POST / DELETE。
            path: API 路徑。
            params: 請求參數。
            timeout: 逾時秒數。
        回傳：
            API JSON 回應內容。
        """
        if not self.api_key:
            raise ValueError("缺少 BINANCE_API_KEY，無法發送簽名請求")

        base_params = dict(params or {})
        base_params.setdefault("timestamp", self._build_timestamp())
        base_params.setdefault("recvWindow", 5000)

        signed_params = self._sign_params(base_params)
        url = self.build_url(path)
        method_upper = method.upper()

        if method_upper == "GET":
            response = self.session.get(
                url, params=signed_params, timeout=timeout)
        elif method_upper == "POST":
            response = self.session.post(
                url, params=signed_params, timeout=timeout)
        elif method_upper == "DELETE":
            response = self.session.delete(
                url, params=signed_params, timeout=timeout)
        else:
            raise ValueError(f"不支援的 HTTP method：{method}")

        response.raise_for_status()
        return response.json()

    def get_signed(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """
        功能：發送 Binance 私有 GET 請求。
        """
        return self.send_signed_request("GET", path, params=params, timeout=timeout)

    def post_signed(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """
        功能：發送 Binance 私有 POST 請求。
        """
        return self.send_signed_request("POST", path, params=params, timeout=timeout)

    def delete_signed(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """
        功能：發送 Binance 私有 DELETE 請求。
        """
        return self.send_signed_request("DELETE", path, params=params, timeout=timeout)

    def get_account_trades(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        limit: int = 100,
        timeout: int = 10,
    ) -> Any:
        """
        功能：查詢 Binance Futures 帳戶成交明細（userTrades）。
        參數：
            symbol: 交易標的，例如 BTCUSDT。
            order_id: 指定某一筆 orderId 的成交明細。
            limit: 回傳筆數上限。
            timeout: 逾時秒數。
        回傳：
            成交明細列表。
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "limit": limit,
        }

        if order_id is not None:
            params["orderId"] = order_id

        return self.get_signed("/fapi/v1/userTrades", params=params, timeout=timeout)

    def get_position_risk(
        self,
        *,
        symbol: str | None = None,
        timeout: int = 10,
    ) -> Any:
        """
        功能：查詢 Binance Futures 持倉風險資料。
        參數：
            symbol: 交易標的；若提供則只查該標的。
            timeout: 逾時秒數。
        回傳：
            持倉資料列表。
        """
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol

        return self.get_signed("/fapi/v3/positionRisk", params=params, timeout=timeout)
