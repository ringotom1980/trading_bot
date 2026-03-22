"""
Path: exchange/order_executor.py
說明：Binance 訂單執行層，封裝市場單、查單、撤單與 reduce-only 平倉請求，供 live_executor 使用。
"""

from __future__ import annotations

from typing import Any

from exchange.binance_client import BinanceClient


def place_market_order(
    client: BinanceClient,
    *,
    symbol: str,
    side: str,
    quantity: float,
    reduce_only: bool = False,
    new_client_order_id: str | None = None,
) -> dict[str, Any]:
    """
    功能：送出 Binance Futures MARKET 訂單。
    """
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
    }

    if reduce_only:
        params["reduceOnly"] = "true"

    if new_client_order_id:
        params["newClientOrderId"] = new_client_order_id

    return client.post_signed("/fapi/v1/order", params=params)


def get_order(
    client: BinanceClient,
    *,
    symbol: str,
    order_id: int | None = None,
    orig_client_order_id: str | None = None,
) -> dict[str, Any]:
    """
    功能：查詢 Binance Futures 訂單。
    """
    params: dict[str, Any] = {"symbol": symbol}

    if order_id is not None:
        params["orderId"] = order_id
    elif orig_client_order_id:
        params["origClientOrderId"] = orig_client_order_id
    else:
        raise ValueError("order_id 與 orig_client_order_id 至少需提供一個")

    return client.get_signed("/fapi/v1/order", params=params)


def cancel_order(
    client: BinanceClient,
    *,
    symbol: str,
    order_id: int | None = None,
    orig_client_order_id: str | None = None,
) -> dict[str, Any]:
    """
    功能：撤銷 Binance Futures 訂單。
    """
    params: dict[str, Any] = {"symbol": symbol}

    if order_id is not None:
        params["orderId"] = order_id
    elif orig_client_order_id:
        params["origClientOrderId"] = orig_client_order_id
    else:
        raise ValueError("order_id 與 orig_client_order_id 至少需提供一個")

    return client.delete_signed("/fapi/v1/order", params=params)


def close_position_reduce_only(
    client: BinanceClient,
    *,
    symbol: str,
    side: str,
    quantity: float,
    new_client_order_id: str | None = None,
) -> dict[str, Any]:
    """
    功能：送出 reduce-only MARKET 平倉單。
    """
    return place_market_order(
        client,
        symbol=symbol,
        side=side,
        quantity=quantity,
        reduce_only=True,
        new_client_order_id=new_client_order_id,
    )
    
    
def get_order_by_exchange_id(
    client: BinanceClient,
    *,
    symbol: str,
    exchange_order_id: str,
) -> dict[str, Any]:
    """
    功能：依 Binance exchange_order_id 查詢訂單。
    """
    return get_order(
        client,
        symbol=symbol,
        order_id=int(exchange_order_id),
    )
    

def get_order_trades(
    client: BinanceClient,
    *,
    symbol: str,
    exchange_order_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    功能：依 Binance exchange_order_id 查詢該委託的成交明細列表。
    """
    response = client.get_account_trades(
        symbol=symbol,
        order_id=int(exchange_order_id),
        limit=limit,
    )
    return list(response or [])


def calculate_trade_fee_summary(
    trades: list[dict[str, Any]],
) -> tuple[float, str | None]:
    """
    功能：加總成交明細中的 commission，回傳總手續費與手續費資產。
    回傳：
        (fee_total, fee_asset)
    """
    fee_total = 0.0
    fee_asset: str | None = None

    for trade in trades:
        commission = float(trade.get("commission") or 0.0)
        fee_total += abs(commission)

        if fee_asset is None:
            commission_asset = trade.get("commissionAsset")
            if commission_asset:
                fee_asset = str(commission_asset)

    return fee_total, fee_asset