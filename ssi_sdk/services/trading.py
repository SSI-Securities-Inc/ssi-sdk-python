"""Trading service (Order, Condition Order, Max Buy/Sell) — async and sync."""

from __future__ import annotations

import logging

from ssi_sdk.constant import EP_TRADING_MAX_BUY_SELL, EP_TRADING_ORDER, HEADER_SIGNATURE
from ssi_sdk.enums import OrderSide, OrderType
from ssi_sdk.models import (
    CancelOrderRequest,
    CancelOrderResponse,
    MaxBuySellRequest,
    MaxBuySellResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
)
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.utils import (
    generate_request_id,
    require_empty,
    require_non_empty,
    require_non_negative,
    require_positive,
    sign,
)

logger = logging.getLogger("ssi_sdk.services.trading")


# ── shared logic ─────────────────────────────────────────────


def _build_place_order(
    account_no: str,
    symbol: str,
    side: OrderSide,
    quantity: int,
    price: float,
    order_type: OrderType,
) -> PlaceOrderRequest:
    """Validate inputs and build a signed place-order request payload."""
    require_non_empty(account_no, "accountNo")
    require_non_empty(symbol, "symbol")
    require_non_empty(side, "side")
    require_non_empty(order_type, "orderType")
    return PlaceOrderRequest(
        account_no=account_no,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        client_request_id=generate_request_id(),
    )


def _build_modify_order(
    account_no: str,
    order_id: str | None,
    client_request_id: str | None,
    price: float | None,
    quantity: int | None,
) -> ModifyOrderRequest:
    """Validate inputs and build a modify-order request payload."""
    require_non_empty(account_no, "accountNo")
    if price is not None:
        require_non_negative(price, "price")
        require_empty(quantity, "quantity")
    if quantity is not None:
        require_positive(quantity, "quantity")
        require_empty(price, "price")
    return ModifyOrderRequest(
        account_no=account_no,
        quantity=quantity,
        price=price,
        order_id=order_id,
        client_request_id=client_request_id,
        client_modify_id=generate_request_id(),
    )


def _build_cancel_order(
    account_no: str,
    order_id: str | None,
    client_request_id: str | None,
) -> CancelOrderRequest:
    """Validate inputs and build a cancel-order request payload."""
    require_non_empty(account_no, "accountNo")
    return CancelOrderRequest(
        account_no=account_no,
        order_id=order_id,
        client_request_id=client_request_id,
        client_cancel_id=generate_request_id(),
    )


def _build_max_buy_sell(account_no: str, symbol: str, price: int | float | None) -> dict:
    """Validate inputs and build the max-buy/sell query parameters dict."""
    require_non_empty(account_no, "accountNo")
    require_non_empty(symbol, "symbol")
    return MaxBuySellRequest(account_no=account_no, symbol=symbol, price=price).to_dict()


def _sign_and_encode(request_model, private_key: str) -> tuple[bytes, str]:
    """Serialize the request model and return its UTF-8 body bytes and signature."""
    body_str = request_model.to_str()
    signature = sign(body_str, private_key)
    return body_str.encode("utf-8"), signature


# ── async class ──────────────────────────────────────────────


class AsyncTradingService:
    """Async trading operations: place/cancel/modify orders."""

    def __init__(self, rest_client: AsyncRestClient):
        """Initialize the service with an async REST client."""
        self._rest = rest_client

    async def _place_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType,
    ) -> PlaceOrderResponse:
        """Build, sign, and POST a place-order request, returning the parsed response."""
        req = _build_place_order(account_no, symbol, side, quantity, price, order_type)
        content, sig = _sign_and_encode(req, self._rest.get_private_key())
        data = await self._rest.post(
            EP_TRADING_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return PlaceOrderResponse.from_dict(data)

    async def place_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType,
    ) -> PlaceOrderResponse:
        """Place a new order of any order type.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Order price in VND (0 for non-priced order types).
            order_type: Order type (LO, MTL, ATO, ATC, ...).
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing or the price is negative.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_negative(price, "price")
        return await self._place_order(account_no, symbol, side, quantity, price, order_type)

    async def place_limit_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> PlaceOrderResponse:
        """Place a limit (LO) order at a specified price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Limit price in VND.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing or the price is not positive.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_positive(price, "price")
        return await self.place_order(account_no, symbol, side, quantity, price, OrderType.LO)

    async def place_market_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> PlaceOrderResponse:
        """Place a market (MTL) order to execute at the best available price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return await self.place_order(
            account_no, symbol, side, quantity, price=0, order_type=OrderType.MTL
        )

    async def place_ato_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> PlaceOrderResponse:
        """Place an at-the-open (ATO) order matched at the opening auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return await self.place_order(
            account_no, symbol, side, quantity, price=0, order_type=OrderType.ATO
        )

    async def place_atc_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> PlaceOrderResponse:
        """Place an at-the-close (ATC) order matched at the closing auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return await self.place_order(
            account_no, symbol, side, quantity, price=0, order_type=OrderType.ATC
        )

    async def _modify_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
        price: float | None = None,
        quantity: int | None = None,
    ) -> ModifyOrderResponse:
        """Build, sign, and PUT a modify-order request, returning the parsed response."""
        req = _build_modify_order(account_no, order_id, client_request_id, price, quantity)
        content, sig = _sign_and_encode(req, self._rest.get_private_key())
        data = await self._rest.put(
            EP_TRADING_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return ModifyOrderResponse.from_dict(data)

    async def modify_order_price(
        self,
        account_no: str,
        client_request_id: str,
        price: float,
    ) -> ModifyOrderResponse:
        """Modify the price of an existing order identified by client request ID.

        Args:
            account_no: Trading account number.
            client_request_id: Caller-assigned order id used to locate the order.
            price: New order price in VND.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(price, "price")
        return await self._modify_order(
            account_no=account_no, client_request_id=client_request_id, price=price
        )

    async def modify_order_price_by_order_id(
        self,
        account_no: str,
        order_id: str,
        price: float,
    ) -> ModifyOrderResponse:
        """Modify the price of an existing order identified by server order ID.

        Args:
            account_no: Trading account number.
            order_id: Server-assigned order id used to locate the order.
            price: New order price in VND.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(price, "price")
        return await self._modify_order(account_no=account_no, order_id=order_id, price=price)

    async def modify_order_quantity(
        self,
        account_no: str,
        client_request_id: str,
        quantity: int,
    ) -> ModifyOrderResponse:
        """Modify the quantity of an existing order identified by client request ID.

        Args:
            account_no: Trading account number.
            client_request_id: Caller-assigned order id used to locate the order.
            quantity: New number of shares.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(quantity, "quantity")
        return await self._modify_order(
            account_no=account_no, client_request_id=client_request_id, quantity=quantity
        )

    async def modify_order_quantity_by_order_id(
        self,
        account_no: str,
        order_id: str,
        quantity: int,
    ) -> ModifyOrderResponse:
        """Modify the quantity of an existing order identified by server order ID.

        Args:
            account_no: Trading account number.
            order_id: Server-assigned order id used to locate the order.
            quantity: New number of shares.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(quantity, "quantity")
        return await self._modify_order(account_no=account_no, order_id=order_id, quantity=quantity)

    async def _cancel_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
    ) -> CancelOrderResponse:
        """Build, sign, and DELETE a cancel-order request, returning the parsed response."""
        req = _build_cancel_order(account_no, order_id, client_request_id)
        content, sig = _sign_and_encode(req, self._rest.get_private_key())
        data = await self._rest.delete(
            EP_TRADING_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return CancelOrderResponse.from_dict(data)

    async def cancel_order(self, account_no: str, client_request_id: str) -> CancelOrderResponse:
        """Cancel an existing order identified by client request ID.

        Args:
            account_no: Trading account number.
            client_request_id: Caller-assigned order id used to locate the order.
        Returns:
            The cancel order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(client_request_id, "clientRequestId")
        return await self._cancel_order(account_no=account_no, client_request_id=client_request_id)

    async def cancel_order_by_order_id(self, account_no: str, order_id: str) -> CancelOrderResponse:
        """Cancel an existing order identified by server order ID.

        Args:
            account_no: Trading account number.
            order_id: Server-assigned order id used to locate the order.
        Returns:
            The cancel order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(order_id, "orderId")
        return await self._cancel_order(account_no=account_no, order_id=order_id)

    async def _get_max_buy_sell(
        self,
        account_no: str,
        symbol: str,
        price: int | float | None = None,
    ) -> MaxBuySellResponse:
        """Build params and GET the max-buy/sell quantities, returning the parsed response."""
        params = _build_max_buy_sell(account_no, symbol, price)
        data = await self._rest.get(
            EP_TRADING_MAX_BUY_SELL,
            params=params,
        )
        return MaxBuySellResponse.from_dict(data, symbol=symbol)

    async def get_max_buy_sell(
        self,
        account_no: str,
        symbol: str,
        price: int | float,
    ) -> MaxBuySellResponse:
        """Get the maximum buy/sell quantities for a symbol at a given price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            price: Reference price in VND used for the calculation.
        Returns:
            The maximum buy/sell quantities response from the server.
        Raises:
            ValidationError: If a required field is missing or the price is not positive.
            APIError: If the server rejects the request.
            AuthenticationError: If authentication fails.
        """
        require_positive(float(price), "price")
        return await self._get_max_buy_sell(account_no, symbol, price)

    async def get_max_buy_sell_at_market_price(
        self,
        account_no: str,
        symbol: str,
    ) -> MaxBuySellResponse:
        """Get the maximum buy/sell quantities for a symbol at the current market price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            The maximum buy/sell quantities response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If authentication fails.
        """
        return await self._get_max_buy_sell(account_no, symbol)


# ── sync class ───────────────────────────────────────────────


class TradingService:
    """Synchronous trading operations: place/cancel/modify orders."""

    def __init__(self, rest_client: RestClient):
        """Initialize the service with a sync REST client."""
        self._rest = rest_client

    def _place_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType,
    ) -> PlaceOrderResponse:
        """Build, sign, and POST a place-order request, returning the parsed response."""
        req = _build_place_order(account_no, symbol, side, quantity, price, order_type)
        content, sig = _sign_and_encode(req, self._rest.get_private_key())
        data = self._rest.post(
            EP_TRADING_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return PlaceOrderResponse.from_dict(data)

    def place_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType,
    ) -> PlaceOrderResponse:
        """Place a new order of any order type.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Order price in VND (0 for non-priced order types).
            order_type: Order type (LO, MTL, ATO, ATC, ...).
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing or the price is negative.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_negative(price, "price")
        return self._place_order(account_no, symbol, side, quantity, price, order_type)

    def place_limit_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> PlaceOrderResponse:
        """Place a limit (LO) order at a specified price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Limit price in VND.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing or the price is not positive.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_positive(price, "price")
        return self.place_order(account_no, symbol, side, quantity, price, OrderType.LO)

    def place_market_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> PlaceOrderResponse:
        """Place a market (MTL) order to execute at the best available price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return self.place_order(
            account_no, symbol, side, quantity, price=0, order_type=OrderType.MTL
        )

    def place_ato_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> PlaceOrderResponse:
        """Place an at-the-open (ATO) order matched at the opening auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return self.place_order(
            account_no, symbol, side, quantity, price=0, order_type=OrderType.ATO
        )

    def place_atc_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> PlaceOrderResponse:
        """Place an at-the-close (ATC) order matched at the closing auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
        Returns:
            The placed order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return self.place_order(
            account_no, symbol, side, quantity, price=0, order_type=OrderType.ATC
        )

    def _modify_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
        price: float | None = None,
        quantity: int | None = None,
    ) -> ModifyOrderResponse:
        """Build, sign, and PUT a modify-order request, returning the parsed response."""
        req = _build_modify_order(account_no, order_id, client_request_id, price, quantity)
        content, sig = _sign_and_encode(req, self._rest.get_private_key())
        data = self._rest.put(
            EP_TRADING_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return ModifyOrderResponse.from_dict(data)

    def modify_order_price(
        self,
        account_no: str,
        client_request_id: str,
        price: float,
    ) -> ModifyOrderResponse:
        """Modify the price of an existing order identified by client request ID.

        Args:
            account_no: Trading account number.
            client_request_id: Caller-assigned order id used to locate the order.
            price: New order price in VND.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(price, "price")
        return self._modify_order(
            account_no=account_no, client_request_id=client_request_id, price=price
        )

    def modify_order_price_by_order_id(
        self,
        account_no: str,
        order_id: str,
        price: float,
    ) -> ModifyOrderResponse:
        """Modify the price of an existing order identified by server order ID.

        Args:
            account_no: Trading account number.
            order_id: Server-assigned order id used to locate the order.
            price: New order price in VND.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(price, "price")
        return self._modify_order(account_no=account_no, order_id=order_id, price=price)

    def modify_order_quantity(
        self,
        account_no: str,
        client_request_id: str,
        quantity: int,
    ) -> ModifyOrderResponse:
        """Modify the quantity of an existing order identified by client request ID.

        Args:
            account_no: Trading account number.
            client_request_id: Caller-assigned order id used to locate the order.
            quantity: New number of shares.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(quantity, "quantity")
        return self._modify_order(
            account_no=account_no, client_request_id=client_request_id, quantity=quantity
        )

    def modify_order_quantity_by_order_id(
        self,
        account_no: str,
        order_id: str,
        quantity: int,
    ) -> ModifyOrderResponse:
        """Modify the quantity of an existing order identified by server order ID.

        Args:
            account_no: Trading account number.
            order_id: Server-assigned order id used to locate the order.
            quantity: New number of shares.
        Returns:
            The modify order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(quantity, "quantity")
        return self._modify_order(account_no=account_no, order_id=order_id, quantity=quantity)

    def _cancel_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
    ) -> CancelOrderResponse:
        """Build, sign, and DELETE a cancel-order request, returning the parsed response."""
        req = _build_cancel_order(account_no, order_id, client_request_id)
        content, sig = _sign_and_encode(req, self._rest.get_private_key())
        data = self._rest.delete(
            EP_TRADING_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return CancelOrderResponse.from_dict(data)

    def cancel_order(self, account_no: str, client_request_id: str) -> CancelOrderResponse:
        """Cancel an existing order identified by client request ID.

        Args:
            account_no: Trading account number.
            client_request_id: Caller-assigned order id used to locate the order.
        Returns:
            The cancel order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(client_request_id, "clientRequestId")
        return self._cancel_order(account_no=account_no, client_request_id=client_request_id)

    def cancel_order_by_order_id(self, account_no: str, order_id: str) -> CancelOrderResponse:
        """Cancel an existing order identified by server order ID.

        Args:
            account_no: Trading account number.
            order_id: Server-assigned order id used to locate the order.
        Returns:
            The cancel order response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_non_empty(order_id, "orderId")
        return self._cancel_order(account_no=account_no, order_id=order_id)

    def _get_max_buy_sell(
        self,
        account_no: str,
        symbol: str,
        price: int | float | None = None,
    ) -> MaxBuySellResponse:
        """Build params and GET the max-buy/sell quantities, returning the parsed response."""
        params = _build_max_buy_sell(account_no, symbol, price)
        data = self._rest.get(
            EP_TRADING_MAX_BUY_SELL,
            params=params,
        )
        return MaxBuySellResponse.from_dict(data, symbol=symbol)

    def get_max_buy_sell(
        self,
        account_no: str,
        symbol: str,
        price: int | float,
    ) -> MaxBuySellResponse:
        """Get the maximum buy/sell quantities for a symbol at a given price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            price: Reference price in VND used for the calculation.
        Returns:
            The maximum buy/sell quantities response from the server.
        Raises:
            ValidationError: If a required field is missing or the price is not positive.
            APIError: If the server rejects the request.
            AuthenticationError: If authentication fails.
        """
        require_positive(float(price), "price")
        return self._get_max_buy_sell(account_no, symbol, price)

    def get_max_buy_sell_at_market_price(
        self,
        account_no: str,
        symbol: str,
    ) -> MaxBuySellResponse:
        """Get the maximum buy/sell quantities for a symbol at the current market price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            The maximum buy/sell quantities response from the server.
        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If authentication fails.
        """
        return self._get_max_buy_sell(account_no, symbol)
