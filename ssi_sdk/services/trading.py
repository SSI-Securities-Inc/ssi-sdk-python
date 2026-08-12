"""Trading service (Order, Condition Order, Max Buy/Sell) — async and sync."""

from __future__ import annotations

import logging

from ssi_sdk.constant import (
    EP_TRADING_MAX_BUY_SELL,
    EP_TRADING_ORDER,
    HEADER_SIGNATURE,
    EP_TRADING_FCO_ORDER,
    EP_TRADING_FCO_LIST,
    EP_TRADING_FCO_ORDER_BOOK,
)
from ssi_sdk.enums import OrderSide, OrderType, FCOOperator, FCOType
from ssi_sdk.models import (
    CancelOrderRequest,
    CancelOrderResponse,
    MaxBuySellRequest,
    MaxBuySellResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
    FCOInfo,
    FCOListRequest,
    FCOListResponse,
    FCOOrderBookRequest,
    FCOOrderBookResponse,
    FCOPlaceResponse,
    FCOCancelRequest,
    FCOCancelResponse,
    GTDParams,
    StopParams,
    TrailingStopParams,
    OCOParams,
    BullBearParams,
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


def _build_fco_list(
    account_no: str,
    fco_id: str | None,
    type: str | None,
    process_status: str | None,
    symbol: str | None,
    side: str | None,
    from_date: str | None,
    to_date: str | None,
    page_index: int | None,
    page_size: int | None,
) -> dict:
    """Validate inputs and build the FCO list request payload."""
    require_non_empty(account_no, "accountNo")
    return FCOListRequest(
        account_no=account_no,
        fco_id=fco_id,
        type=type,
        process_status=process_status,
        symbol=symbol,
        side=side,
        from_date=from_date,
        to_date=to_date,
        page_index=page_index,
        page_size=page_size,
    ).to_dict()


def _build_fco_params(params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams) -> dict:
    """Validate inputs and build the FCO params dict."""
    if isinstance(params, GTDParams):
        return params
    elif isinstance(params, StopParams):
        return params
    elif isinstance(params, TrailingStopParams):
        return params
    elif isinstance(params, OCOParams):
        return params
    elif isinstance(params, BullBearParams):
        return params
    else:
        raise ValueError("Invalid FCO params type")


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

    async def _get_fco_list(
        self,
        account_no: str,
        fco_id: str | None = None,
        type: str | None = None,
        process_status: str | None = None,

        symbol: str | None = None,
        side: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get the list of FCO orders with pagination and filtering."""
        params = _build_fco_list(
            account_no=account_no,
            fco_id=fco_id,
            type=type,
            process_status=process_status,
            symbol=symbol,
            side=side,
            from_date=from_date,
            to_date=to_date,
            page_index=page_index,
            page_size=page_size,
        )
        data = await self._rest.get(EP_TRADING_FCO_LIST, params=params)
        return FCOListResponse.from_dict(data)

    async def get_fco_by_account_no(
        self,
        account_no: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get all FCO orders for a trading account."""
        return await self._get_fco_list(
            account_no=account_no,
            page_index=page_index,
            page_size=page_size,
        )

    async def get_fco_by_symbol(
        self,
        account_no: str,
        symbol: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by stock or derivative symbol."""
        return await self._get_fco_list(
            account_no=account_no,
            symbol=symbol,
            page_index=page_index,
            page_size=page_size,
        )

    async def get_fco_by_status(
        self,
        account_no: str,
        process_status: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by processing status."""
        return await self._get_fco_list(
            account_no=account_no,
            process_status=process_status,
            page_index=page_index,
            page_size=page_size,
        )

    async def get_fco_by_date(
        self,
        account_no: str,
        from_date: str,
        to_date: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by date range."""
        return await self._get_fco_list(
            account_no=account_no,
            from_date=from_date,
            to_date=to_date,
            page_index=page_index,
            page_size=page_size,
        )

    async def get_fco_by_id(
        self,
        account_no: str,
        fco_id: str,
    ) -> FCOInfo | None:
        """Get a single FCO order by FCO ID."""
        response = await self._get_fco_list(
            account_no=account_no,
            fco_id=fco_id,
        )
        return response.fco_list[0] if response.fco_list else None

    async def get_fco_order_book(
        self,
        fco_id: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOOrderBookResponse:
        """Get the order book/history of a conditional FCO order.

        Args:
            fco_id: FCO order ID.
            page_index: Page number index, starting from 1. Default is 1 (optional).
            page_size: Number of records per page. Default is 10 (optional).
        Returns:
            FCOOrderBookResponse containing the paginated FCO order book entries.
        """
        require_non_empty(fco_id, "fcoId")
        params = FCOOrderBookRequest(
            fco_id=fco_id,
            page_index=page_index if page_index is not None else 1,
            page_size=page_size if page_size is not None else 10,
        ).to_dict()
        data = await self._rest.get(EP_TRADING_FCO_ORDER_BOOK, params=params)
        return FCOOrderBookResponse.from_dict(data)

    async def _place_fco(
        self,
        params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams,
    ) -> FCOPlaceResponse:
        """Place a conditional (FCO) order."""
        _params = _build_fco_params(params)
        content, sig = _sign_and_encode(_params, self._rest.get_private_key())
        data = await self._rest.post(
            EP_TRADING_FCO_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return FCOPlaceResponse.from_dict(data)

    async def place_fco_gtd(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | OrderType,
        price_slip: float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a GTD order."""
        if isinstance(price, OrderType):
            price = price.value
            price_slip = 0
        params = GTDParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            price_slip=price_slip,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def place_fco_stop(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_price: int | float,
        operator: FCOOperator,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a stop order."""
        params = StopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            price=OrderType.MTL,
            price_slip=0,
            quantity=quantity,
            stop_price=stop_price,
            operator=operator,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def place_fco_stop_limit(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: int | float,
        price_slip: float,
        stop_price: int | float,
        operator: FCOOperator,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a stop limit order."""
        params = StopParams(
            account_no=account_no,
            fco_type=FCOType.STOP_LIMIT,
            symbol=symbol,
            side=side,
            price=price,
            price_slip=price_slip,
            quantity=quantity,
            stop_price=stop_price,
            operator=operator,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def place_fco_trailing_stop(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: int | float,
        trailing_amount: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a trailing stop order."""
        params = TrailingStopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            active_price=active_price,
            trailing_amount=trailing_amount,
            quantity=quantity,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def place_fco_trailing_stop_limit(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: int | float,
        trailing_amount: int | float,
        price_slip: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a trailing stop limit order."""
        params = TrailingStopParams(
            account_no=account_no,
            fco_type=FCOType.TRAILING_STOP_LIMIT,
            symbol=symbol,
            side=side,
            active_price=active_price,
            trailing_amount=trailing_amount,
            price_slip=price_slip,
            quantity=quantity,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def place_fco_oco(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        tp_active_price: int | float,
        sl_active_price: int | float,
        tp_price: int | float | OrderType,
        sl_price: int | float | OrderType,
        tp_slip: int | float,
        sl_slip: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place an OCO order."""
        params = OCOParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            quantity=quantity,
            tp_active_price=tp_active_price,
            sl_active_price=sl_active_price,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_slip=tp_slip,
            sl_slip=sl_slip,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def place_fco_bull_bear(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: int | float,
        price_slip: int | float,
        tp_active_price: int | float,
        sl_active_price: int | float,
        tp_price: int | float | OrderType,
        sl_price: int | float | OrderType,
        tp_slip: int | float,
        sl_slip: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a Bull Bear order."""
        params = BullBearParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            price_slip=price_slip,
            tp_active_price=tp_active_price,
            sl_active_price=sl_active_price,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_slip=tp_slip,
            sl_slip=sl_slip,
            from_date=from_date,
            to_date=to_date,
        )
        return await self._place_fco(params)

    async def cancel_fco(self, fco_id: str) -> FCOCancelResponse:
        """Cancel a FCO."""
        params = FCOCancelRequest(fco_id=fco_id)
        content, sig = _sign_and_encode(params, self._rest.get_private_key())
        data = await self._rest.delete(
            EP_TRADING_FCO_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return FCOCancelResponse.from_dict(data)


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

    def _get_fco_list(
        self,
        account_no: str,
        fco_id: str | None = None,
        type: str | None = None,
        process_status: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get the list of FCO orders with pagination and filtering.

        Args:
            account_no: Trading account number.
            fco_id: FCO ID to query (optional).
            type: FCO type (optional).
            process_status: FCO processing status, comma separated for multiple statuses (optional).
            symbol: Stock symbol or derivative contract code (optional).
            side: Side of the order (optional).
            from_date: Start date, YYYY/MM/DD format (optional).
            to_date: End date, YYYY/MM/DD format (optional).
            page_index: Page number index, starting from 1. Default is 1 (optional).
            page_size: Number of records per page. Default is 10 (optional).
        Returns:
            FCOListResponse containing the paginated FCO orders and metadata.
        """
        params = _build_fco_list(
            account_no=account_no,
            fco_id=fco_id,
            type=type,
            process_status=process_status,
            symbol=symbol,
            side=side,
            from_date=from_date,
            to_date=to_date,
            page_index=page_index,
            page_size=page_size,
        )
        data = self._rest.get(EP_TRADING_FCO_LIST, params=params)
        return FCOListResponse.from_dict(data)

    def get_fco_by_account_no(
        self,
        account_no: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get all FCO orders for a trading account."""
        return self._get_fco_list(
            account_no=account_no,
            page_index=page_index,
            page_size=page_size,
        )

    def get_fco_by_symbol(
        self,
        account_no: str,
        symbol: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by stock or derivative symbol."""
        return self._get_fco_list(
            account_no=account_no,
            symbol=symbol,
            page_index=page_index,
            page_size=page_size,
        )

    def get_fco_by_status(
        self,
        account_no: str,
        process_status: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by processing status."""
        return self._get_fco_list(
            account_no=account_no,
            process_status=process_status,
            page_index=page_index,
            page_size=page_size,
        )

    def get_fco_by_date(
        self,
        account_no: str,
        from_date: str,
        to_date: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by date range."""
        return self._get_fco_list(
            account_no=account_no,
            from_date=from_date,
            to_date=to_date,
            page_index=page_index,
            page_size=page_size,
        )

    def get_fco_by_id(
        self,
        account_no: str,
        fco_id: str,
    ) -> FCOInfo | None:
        """Get a single FCO order by FCO ID."""
        response = self._get_fco_list(
            account_no=account_no,
            fco_id=fco_id,
        )
        return response.fco_list[0] if response.fco_list else None

    def get_fco_order_book(
        self,
        fco_id: str,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOOrderBookResponse:
        """Get the order book/history of a conditional FCO order.

        Args:
            fco_id: FCO order ID.
            page_index: Page number index, starting from 1. Default is 1 (optional).
            page_size: Number of records per page. Default is 10 (optional).
        Returns:
            FCOOrderBookResponse containing the paginated FCO order book entries.
        """
        require_non_empty(fco_id, "fcoId")
        params = FCOOrderBookRequest(
            fco_id=fco_id,
            page_index=page_index if page_index is not None else 1,
            page_size=page_size if page_size is not None else 10,
        ).to_dict()
        data = self._rest.get(EP_TRADING_FCO_ORDER_BOOK, params=params)
        return FCOOrderBookResponse.from_dict(data)

    def _place_fco(
        self,
        params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams,
    ) -> FCOPlaceResponse:
        """Place a conditional (FCO) order."""
        _params = _build_fco_params(params)
        content, sig = _sign_and_encode(_params, self._rest.get_private_key())
        data = self._rest.post(
            EP_TRADING_FCO_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return FCOPlaceResponse.from_dict(data)

    def place_fco_gtd(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | OrderType,
        price_slip: float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a GTD order."""
        if isinstance(price, OrderType):
            price = price.value
            price_slip = 0
        params = GTDParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            price_slip=price_slip,
            from_date=from_date,
            to_date=to_date,
        )
        return self._place_fco(params)
    
    def place_fco_stop(
        self,    
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_price: int | float,
        operator: FCOOperator,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a stop order."""
        params = StopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            price=OrderType.MTL,
            price_slip=0,
            quantity=quantity,
            stop_price=stop_price,
            operator=operator,
            from_date=from_date,
            to_date=to_date
        )
        return self._place_fco(params)

    def place_fco_stop_limit(
        self,    
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: int | float,
        price_slip: float,
        stop_price: int | float,
        operator: FCOOperator,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a stop order."""
        params = StopParams(
            account_no=account_no,
            fco_type=FCOType.STOP_LIMIT,
            symbol=symbol,
            side=side,
            price=price,
            price_slip=price_slip,
            quantity=quantity,
            stop_price=stop_price,
            operator=operator,
            from_date=from_date,
            to_date=to_date
        )
        return self._place_fco(params)

    def place_fco_trailing_stop(
        self,    
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: int | float,
        trailing_amount: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a stop order."""
        params = TrailingStopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            active_price=active_price,
            trailing_amount=trailing_amount,
            quantity=quantity,
            from_date=from_date,
            to_date=to_date
        )
        return self._place_fco(params)

    def place_fco_trailing_stop_limit(
        self,    
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: int | float,
        trailing_amount: int | float,
        price_slip: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a stop order."""
        params = TrailingStopParams(
            account_no=account_no,
            fco_type=FCOType.TRAILING_STOP_LIMIT,
            symbol=symbol,
            side=side,
            active_price=active_price,
            trailing_amount=trailing_amount,
            price_slip=price_slip,
            quantity=quantity,
            from_date=from_date,
            to_date=to_date
        )
        return self._place_fco(params)

    def place_fco_oco(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        tp_active_price: int | float,
        sl_active_price: int | float,
        tp_price: int | float | OrderType,
        sl_price: int | float | OrderType,
        tp_slip: int | float,
        sl_slip: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        """Place a OCO order."""
        params = OCOParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            quantity=quantity,
            tp_active_price=tp_active_price,
            sl_active_price=sl_active_price,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_slip=tp_slip,
            sl_slip=sl_slip,
            from_date=from_date,
            to_date=to_date,
        )
        return self._place_fco(params)

    def place_fco_bull_bear(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: int | float,
        price_slip: int | float,
        tp_active_price: int | float,
        sl_active_price: int | float,
        tp_price: int | float | OrderType,
        sl_price: int | float | OrderType,
        tp_slip: int | float,
        sl_slip: int | float,
        from_date: str,
        to_date: str,
    ) -> FCOPlaceResponse:
        params = BullBearParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            price_slip=price_slip,
            tp_active_price=tp_active_price,
            sl_active_price=sl_active_price,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_slip=tp_slip,
            sl_slip=sl_slip,
            from_date=from_date,
            to_date=to_date,
        )
        return self._place_fco(params)

    def cancel_fco(self, fco_id: str) -> FCOCancelResponse:
        """Cancel a FCO."""
        params = FCOCancelRequest(fco_id=fco_id)
        content, sig = _sign_and_encode(params, self._rest.get_private_key())
        data = self._rest.delete(
            EP_TRADING_FCO_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return FCOCancelResponse.from_dict(data)