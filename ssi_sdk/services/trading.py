"""Trading service (Order, Condition Order, Max Buy/Sell) — async and sync."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    EP_TRADING_FCO_LIST,
    EP_TRADING_FCO_ORDER,
    EP_TRADING_FCO_ORDER_BOOK,
    EP_TRADING_FCO_STATUS_HISTORY,
    EP_TRADING_MAX_BUY_SELL,
    EP_TRADING_ORDER,
    EP_TRADING_ORDER_BATCH,
    HEADER_SIGNATURE,
    MAX_BATCH_ORDERS,
    MAX_CLIENT_REQUEST_ID_LENGTH,
)
from ssi_sdk.enums import (
    FCOOperator,
    FCOOperatorLike,
    FCOStatusLike,
    FCOType,
    FCOTypeLike,
    OrderSide,
    OrderType,
)
from ssi_sdk.exceptions import ValidationError
from ssi_sdk.models import (
    BatchCancelOrderItem,
    BatchOrderRequest,
    BatchOrderResponse,
    BatchPlaceOrderItem,
    BullBearParams,
    CancelOrderRequest,
    CancelOrderResponse,
    FCOCancelRequest,
    FCOCancelResponse,
    FCOInfo,
    FCOListRequest,
    FCOListResponse,
    FCOOrderBookRequest,
    FCOOrderBookResponse,
    FCOPlaceResponse,
    FCOStatusHistoryItem,
    FCOStatusHistoryRequest,
    GTDParams,
    MaxBuySellRequest,
    MaxBuySellResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    NumberLike,
    OCOParams,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PriceLike,
    StopParams,
    TrailingStopParams,
)
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.utils import (
    generate_request_id,
    get_device_id,
    parse_date_arg,
    require_date_range,
    require_exactly_one,
    require_non_empty,
    require_non_negative,
    require_positive,
    sign,
    to_price_decimal,
)

logger = logging.getLogger("ssi_sdk.services.trading")


# ── shared logic ─────────────────────────────────────────────


_PRICED_ORDER_TYPES = (OrderType.LO, OrderType.PLO)


def _operator(value: FCOOperatorLike) -> FCOOperator:
    """Accept an ``FCOOperator`` or its string (``"greater_or_equal"``...); refuse anything else."""
    resolved = FCOOperator.from_value(value)
    if resolved is None:
        allowed = ", ".join(member.value for member in FCOOperator)
        raise ValidationError(f"operator must be one of {allowed}, got {value!r}")
    return resolved


def _identity(config: Config) -> dict:
    """Request fields every order payload takes from ``Config`` (device id, user agent)."""
    identity = {"device_id": get_device_id()}
    if config.user_agent:
        identity["user_agent"] = config.user_agent
    return identity


def _client_request_id(value: str | None) -> str:
    """Use the caller's idempotency key, or generate a random one (<= 20 chars).

    A caller-chosen key lets an order that timed out be looked up (or safely re-sent with
    the same key — the server answers 409 if the first one went through).
    """
    if value is None:
        return generate_request_id()
    require_non_empty(value, "clientRequestId")
    if len(value) > MAX_CLIENT_REQUEST_ID_LENGTH:
        raise ValidationError(
            f"clientRequestId must be at most {MAX_CLIENT_REQUEST_ID_LENGTH} characters"
        )
    return value


def _build_place_order(
    account_no: str,
    symbol: str,
    side: OrderSide,
    quantity: int,
    price: PriceLike | None,
    order_type: OrderType,
    config: Config,
    client_request_id: str | None = None,
) -> PlaceOrderRequest:
    """Validate inputs and build a place-order request payload."""
    require_non_empty(account_no, "accountNo")
    require_non_empty(symbol, "symbol")
    require_non_empty(side, "side")
    require_non_empty(order_type, "orderType")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValidationError(f"quantity must be an integer, got {quantity!r}")
    require_positive(quantity, "quantity")
    if price is None and order_type in _PRICED_ORDER_TYPES:
        raise ValidationError(f"price is required for {order_type.value} orders")
    return PlaceOrderRequest(
        account_no=account_no,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        client_request_id=_client_request_id(client_request_id),
        **_identity(config),
    )


def _build_modify_order(
    account_no: str,
    order_id: str | None,
    client_request_id: str | None,
    price: PriceLike | None,
    quantity: int | None,
    config: Config,
) -> ModifyOrderRequest:
    """Validate inputs and build a modify-order request payload.

    The order is identified by exactly one of ``order_id``/``client_request_id``, and a
    single call changes either the price or the quantity, never both.
    """
    require_non_empty(account_no, "accountNo")
    require_exactly_one(order_id, client_request_id, "orderId", "clientRequestId")
    if price is None and quantity is None:
        raise ValidationError("either price or quantity is required")
    if price is not None and quantity is not None:
        raise ValidationError("price and quantity cannot be modified in the same request")
    if price is not None:
        require_positive(to_price_decimal(price), "price")
    if quantity is not None:
        require_positive(quantity, "quantity")
    return ModifyOrderRequest(
        account_no=account_no,
        quantity=quantity,
        price=price,
        order_id=order_id,
        client_request_id=client_request_id,
        client_modify_id=generate_request_id(),
        **_identity(config),
    )


def _build_cancel_order(
    account_no: str,
    order_id: str | None,
    client_request_id: str | None,
    config: Config,
) -> CancelOrderRequest:
    """Validate inputs and build a cancel-order request payload (exactly one order key)."""
    require_non_empty(account_no, "accountNo")
    require_exactly_one(order_id, client_request_id, "orderId", "clientRequestId")
    return CancelOrderRequest(
        account_no=account_no,
        order_id=order_id,
        client_request_id=client_request_id,
        client_cancel_id=generate_request_id(),
        **_identity(config),
    )


def _build_max_buy_sell(account_no: str, symbol: str, price: PriceLike | None) -> dict:
    """Validate inputs and build the max-buy/sell query parameters dict."""
    require_non_empty(account_no, "accountNo")
    require_non_empty(symbol, "symbol")
    return MaxBuySellRequest(account_no=account_no, symbol=symbol, price=price).to_dict()


def _check_batch(
    orders: Sequence[Mapping[str, Any]], limit: int = MAX_BATCH_ORDERS
) -> list[Mapping[str, Any]]:
    """A batch holds 1..``limit`` orders (``Config.max_batch_orders``, the server's default is
    20); the server rejects bigger ones, so fail early."""
    if not orders:
        raise ValidationError("a batch needs at least one order")
    if len(orders) > limit:
        raise ValidationError(f"a batch holds at most {limit} orders, got {len(orders)}")
    return list(orders)


def _batch_envelope(orders: list[dict]) -> BatchOrderRequest:
    """Batch envelope: a random id (a reused one is a 409) and the current time in epoch ms
    (outside the server's replay window it is a 400111)."""
    return BatchOrderRequest(
        batch_request_id=generate_request_id(),
        batch_request_time=int(time.time() * 1000),
        orders=orders,
    )


def _build_batch_place(orders: Sequence[Mapping[str, Any]], config: Config) -> BatchOrderRequest:
    """Validate every order first (one bad order rejects the whole batch) and build the body.

    Each dict carries the ``place_order`` arguments: ``account_no``, ``symbol``, ``side``,
    ``quantity``, ``price``, ``order_type`` and optionally ``client_request_id``.
    """
    built = [
        _build_place_order(
            item["account_no"],
            item["symbol"],
            item["side"],
            item["quantity"],
            item.get("price"),
            item["order_type"],
            config,
            item.get("client_request_id"),
        ).to_dict()
        for item in _check_batch(orders, config.max_batch_orders)
    ]
    return _batch_envelope(built)


def _build_batch_cancel(orders: Sequence[Mapping[str, Any]], config: Config) -> BatchOrderRequest:
    """Validate every cancel first and build the body (``account_no`` and exactly one of
    ``order_id`` / ``client_request_id`` per order)."""
    built = [
        _build_cancel_order(
            item["account_no"], item.get("order_id"), item.get("client_request_id"), config
        ).to_dict()
        for item in _check_batch(orders, config.max_batch_orders)
    ]
    return _batch_envelope(built)


def _sign_and_encode(request_model, private_key: str) -> tuple[bytes, str]:
    """Serialize the request model and return its UTF-8 body bytes and signature."""
    body_str = request_model.to_str()
    signature = sign(body_str, private_key)
    return body_str.encode("utf-8"), signature


def _build_fco_list(
    account_no: str,
    fco_id: str | None,
    type: FCOTypeLike | None,
    process_status: FCOStatusLike | list[FCOStatusLike] | None,
    symbol: str | None,
    side: OrderSide | str | None,
    from_date: str | None,
    to_date: str | None,
    page_index: int | None,
    page_size: int | None,
) -> dict:
    """Validate inputs and build the FCO list request payload.

    ``from``/``to`` are ``YYYY/MM/DD HH:MM:SS`` (a bare ``YYYY/MM/DD`` is accepted too) and
    ``from <= to``.
    """
    require_non_empty(account_no, "accountNo")
    if from_date is not None and to_date is not None:
        require_date_range(from_date, to_date, allow_time=True)
    else:
        for name, value in (("from", from_date), ("to", to_date)):
            if value is not None:
                parse_date_arg(value, name, allow_time=True)
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


_FCO_PARAM_TYPES = (GTDParams, StopParams, TrailingStopParams, OCOParams, BullBearParams)
_FCO_MAX_RANGE_DAYS = 31


def _build_fco_params(
    params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams,
    config: Config,
) -> GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams:
    """Validate an FCO order and fill in the caller identity from ``Config``.

    The validity window must be ``YYYY/MM/DD HH:MM:SS``, ``from <= to`` and at most 31 days:
    the API contract says so but the server does not check it, so the SDK does. The device id
    is always this machine's (:func:`ssi_sdk.utils.get_device_id`); the server records the IP.
    """
    if not isinstance(params, _FCO_PARAM_TYPES):
        raise ValidationError("Invalid FCO params type")
    if params.from_date is not None and params.to_date is not None:
        require_date_range(
            params.from_date, params.to_date, time_required=True, max_days=_FCO_MAX_RANGE_DAYS
        )
    else:
        for name, value in (("from", params.from_date), ("to", params.to_date)):
            if value is not None:
                parse_date_arg(value, name, time_required=True)
    params.device_id = get_device_id()  # always this machine's id, whatever the caller set
    if config.user_agent:
        params.user_agent = config.user_agent
    return params


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
        price: PriceLike,
        order_type: OrderType,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Build, sign, and POST a place-order request, returning the parsed response."""
        req = _build_place_order(
            account_no,
            symbol,
            side,
            quantity,
            price,
            order_type,
            self._rest.config,
            client_request_id,
        )
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
        price: PriceLike,
        order_type: OrderType,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place a new order of any order type.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Order price in VND (0 for non-priced order types).
            order_type: Order type (LO, MTL, ATO, ATC, ...).
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing or the price is negative.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        if price is not None:
            require_non_negative(to_price_decimal(price), "price")
        return await self._place_order(
            account_no, symbol, side, quantity, price, order_type, client_request_id
        )

    async def place_limit_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: PriceLike,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place a limit (LO) order at a specified price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Limit price in VND.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing or the price is not positive.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_positive(to_price_decimal(price), "price")
        return await self.place_order(
            account_no, symbol, side, quantity, price, OrderType.LO, client_request_id
        )

    async def place_market_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place a market (MTL) order to execute at the best available price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return await self.place_order(
            account_no,
            symbol,
            side,
            quantity,
            price=0,
            order_type=OrderType.MTL,
            client_request_id=client_request_id,
        )

    async def place_ato_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place an at-the-open (ATO) order matched at the opening auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return await self.place_order(
            account_no,
            symbol,
            side,
            quantity,
            price=0,
            order_type=OrderType.ATO,
            client_request_id=client_request_id,
        )

    async def place_atc_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place an at-the-close (ATC) order matched at the closing auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return await self.place_order(
            account_no,
            symbol,
            side,
            quantity,
            price=0,
            order_type=OrderType.ATC,
            client_request_id=client_request_id,
        )

    async def _modify_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
        price: PriceLike | None = None,
        quantity: int | None = None,
    ) -> ModifyOrderResponse:
        """Build, sign, and PUT a modify-order request, returning the parsed response."""
        req = _build_modify_order(
            account_no, order_id, client_request_id, price, quantity, self._rest.config
        )
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
        price: PriceLike,
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
        require_positive(to_price_decimal(price), "price")
        return await self._modify_order(
            account_no=account_no, client_request_id=client_request_id, price=price
        )

    async def modify_order_price_by_order_id(
        self,
        account_no: str,
        order_id: str,
        price: PriceLike,
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
        require_positive(to_price_decimal(price), "price")
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
        req = _build_cancel_order(account_no, order_id, client_request_id, self._rest.config)
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

    async def place_batch_orders(self, orders: list[BatchPlaceOrderItem]) -> BatchOrderResponse:
        """Place a batch of orders in one signed request (``POST /order/batch``).

        At most ``Config.max_batch_orders`` orders (the server's default is 20).

        All orders are validated first and the server accepts or rejects the batch as a whole.
        ``batchRequestId`` is random and ``batchRequestTime`` is the current time; the request
        is signed over the whole body and never retried.

        Args:
            orders: One dict per order with the ``place_order`` arguments (``account_no``,
                    ``symbol``, ``side``, ``quantity``, ``price``, ``order_type`` and optionally
                    ``client_request_id``).

        Returns:
            ``results`` with one entry per order (``client_request_id``, ``order_id``,
            ``status``, ``success``, ``error_code``, ``error_message``).

        Raises:
            ValidationError: Empty batch, over ``Config.max_batch_orders`` orders, or a bad order.
            DuplicateRequestError: The batch id was already used today (HTTP 409).
            APIError: The server rejects the request (e.g. 400111, time outside the window).
        """
        request = _build_batch_place(orders, self._rest.config)
        content, sig = _sign_and_encode(request, self._rest.get_private_key())
        data = await self._rest.post(
            EP_TRADING_ORDER_BATCH, content=content, headers={HEADER_SIGNATURE: sig}
        )
        return BatchOrderResponse.from_dict(data)

    async def cancel_batch_orders(self, orders: list[BatchCancelOrderItem]) -> BatchOrderResponse:
        """Cancel a batch of orders in one signed request (``DELETE /order/batch``).

        At most ``Config.max_batch_orders`` orders (the server's default is 20).

        Args:
            orders: One dict per order: ``account_no`` and exactly one of ``order_id`` /
                    ``client_request_id``.

        Returns:
            ``results`` as for :meth:`place_batch_orders`, plus ``client_cancel_id`` per order.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
        """
        request = _build_batch_cancel(orders, self._rest.config)
        content, sig = _sign_and_encode(request, self._rest.get_private_key())
        data = await self._rest.delete(
            EP_TRADING_ORDER_BATCH, content=content, headers={HEADER_SIGNATURE: sig}
        )
        return BatchOrderResponse.from_dict(data)

    async def _get_max_buy_sell(
        self,
        account_no: str,
        symbol: str,
        price: PriceLike | None = None,
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
        price: PriceLike,
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
        type: FCOTypeLike | None = None,
        process_status: FCOStatusLike | list[FCOStatusLike] | None = None,

        symbol: str | None = None,
        side: OrderSide | str | None = None,
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
        """Get all FCO orders for a trading account.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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
        """Get FCO orders filtered by stock or derivative symbol.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
        return await self._get_fco_list(
            account_no=account_no,
            symbol=symbol,
            page_index=page_index,
            page_size=page_size,
        )

    async def get_fco_by_status(
        self,
        account_no: str,
        process_status: FCOStatusLike | list[FCOStatusLike],
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by processing status.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            process_status: FCO status to filter by: an ``FCOStatus`` member or its string
                            (``"WAIT"``, ``"TRI"``, ...); pass a list to match several.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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
        """Get FCO orders filtered by date range.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            from_date: Start of the date filter, ``"YYYY/MM/DD HH:MM:SS"`` (a bare date is
                       accepted).
            to_date: End of the date filter, same format; must not precede ``from_date``.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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
        """Get a single FCO order by FCO ID.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.

        Returns:
            The ``FCOInfo``, or ``None`` when no such FCO exists for the account.

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
        require_non_empty(fco_id, "fcoId")
        params = FCOOrderBookRequest(
            fco_id=fco_id,
            page_index=page_index if page_index is not None else 1,
            page_size=page_size if page_size is not None else 10,
        ).to_dict()
        data = await self._rest.get(EP_TRADING_FCO_ORDER_BOOK, params=params)
        return FCOOrderBookResponse.from_dict(data)

    async def get_fco_status_history(self, fco_id: str) -> list[FCOStatusHistoryItem]:
        """Get the status transitions of a conditional (FCO) order.

        Args:
            fco_id: Id of the FCO.

        Returns:
            The recorded transitions (state, time, code, detail); empty when there are none.

        Raises:
            ValidationError: If ``fco_id`` is empty.
            APIError: If the server rejects the request.
        """
        require_non_empty(fco_id, "fcoId")
        params = FCOStatusHistoryRequest(fco_id=fco_id).to_dict()
        data = await self._rest.get(EP_TRADING_FCO_STATUS_HISTORY, params=params)
        return FCOStatusHistoryItem.from_response(data)

    async def _place_fco(
        self,
        params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams,
    ) -> FCOPlaceResponse:
        """Place a conditional (FCO) order."""
        _params = _build_fco_params(params, self._rest.config)
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
        price: PriceLike | OrderType,
        price_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a GTD order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return await self._place_fco(params)

    async def place_fco_stop(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_price: NumberLike,
        operator: FCOOperatorLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a stop order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            stop_price: Trigger price of the stop, in VND.
            operator: Comparison that fires the trigger, e.g. ``FCOOperator.GREATER_OR_EQUAL``
                      (fires when price >= ``stop_price``) or ``FCOOperator.LESSER_OR_EQUAL``.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
        params = StopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            price=OrderType.MTL,
            price_slip=0,
            quantity=quantity,
            stop_price=stop_price,
            operator=_operator(operator),
            from_date=from_date,
            to_date=to_date,
            code=code,
        )
        return await self._place_fco(params)

    async def place_fco_stop_limit(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: PriceLike,
        price_slip: NumberLike,
        stop_price: NumberLike,
        operator: FCOOperatorLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a stop limit order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            stop_price: Trigger price of the stop, in VND.
            operator: Comparison that fires the trigger, e.g. ``FCOOperator.GREATER_OR_EQUAL``
                      (fires when price >= ``stop_price``) or ``FCOOperator.LESSER_OR_EQUAL``.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
        params = StopParams(
            account_no=account_no,
            fco_type=FCOType.STOP_LIMIT,
            symbol=symbol,
            side=side,
            price=price,
            price_slip=price_slip,
            quantity=quantity,
            stop_price=stop_price,
            operator=_operator(operator),
            from_date=from_date,
            to_date=to_date,
            code=code,
        )
        return await self._place_fco(params)

    async def place_fco_trailing_stop(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: NumberLike,
        trailing_amount: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a trailing stop order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            active_price: Price at which the trailing stop becomes active, in VND.
            trailing_amount: Distance in VND the price must retrace from its best level to fire
                             the stop.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
        params = TrailingStopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            active_price=active_price,
            trailing_amount=trailing_amount,
            quantity=quantity,
            from_date=from_date,
            to_date=to_date,
            code=code,
        )
        return await self._place_fco(params)

    async def place_fco_trailing_stop_limit(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: NumberLike,
        trailing_amount: NumberLike,
        price_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a trailing stop limit order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            active_price: Price at which the trailing stop becomes active, in VND.
            trailing_amount: Distance in VND the price must retrace from its best level to fire
                             the stop.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return await self._place_fco(params)

    async def place_fco_oco(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        tp_active_price: NumberLike,
        sl_active_price: NumberLike,
        tp_price: PriceLike | OrderType,
        sl_price: PriceLike | OrderType,
        tp_slip: NumberLike,
        sl_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place an OCO order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            tp_active_price: Take-profit trigger price, in VND.
            sl_active_price: Stop-loss trigger price, in VND.
            tp_price: Order price once take-profit fires: a number, or an ``OrderType`` word.
            sl_price: Order price once stop-loss fires: a number, or an ``OrderType`` word.
            tp_slip: Slippage in VND allowed on the take-profit order.
            sl_slip: Slippage in VND allowed on the stop-loss order.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return await self._place_fco(params)

    async def place_fco_bull_bear(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: PriceLike,
        price_slip: NumberLike,
        tp_active_price: NumberLike,
        sl_active_price: NumberLike,
        tp_price: PriceLike | OrderType,
        sl_price: PriceLike | OrderType,
        tp_slip: NumberLike,
        sl_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a Bull Bear order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            tp_active_price: Take-profit trigger price, in VND.
            sl_active_price: Stop-loss trigger price, in VND.
            tp_price: Order price once take-profit fires: a number, or an ``OrderType`` word.
            sl_price: Order price once stop-loss fires: a number, or an ``OrderType`` word.
            tp_slip: Slippage in VND allowed on the take-profit order.
            sl_slip: Slippage in VND allowed on the stop-loss order.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return await self._place_fco(params)

    async def cancel_fco(self, fco_id: str, code: str | None = None) -> FCOCancelResponse:
        """Cancel a FCO.

        Args:
            fco_id: Id of the conditional order to cancel.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            The cancelled FCO id.

        Raises:
            ValidationError: If ``fco_id`` is empty.
            APIError: If the server rejects the request.
        """
        require_non_empty(fco_id, "fcoId")
        config = self._rest.config
        params = FCOCancelRequest(
            fco_id=fco_id,
            device_id=get_device_id(),
            user_agent=config.user_agent,
            code=code,
        )
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
        price: PriceLike,
        order_type: OrderType,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Build, sign, and POST a place-order request, returning the parsed response."""
        req = _build_place_order(
            account_no,
            symbol,
            side,
            quantity,
            price,
            order_type,
            self._rest.config,
            client_request_id,
        )
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
        price: PriceLike,
        order_type: OrderType,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place a new order of any order type.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Order price in VND (0 for non-priced order types).
            order_type: Order type (LO, MTL, ATO, ATC, ...).
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing or the price is negative.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        if price is not None:
            require_non_negative(to_price_decimal(price), "price")
        return self._place_order(
            account_no, symbol, side, quantity, price, order_type, client_request_id
        )

    def place_limit_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: PriceLike,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place a limit (LO) order at a specified price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            price: Limit price in VND.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing or the price is not positive.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        require_positive(to_price_decimal(price), "price")
        return self.place_order(
            account_no, symbol, side, quantity, price, OrderType.LO, client_request_id
        )

    def place_market_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place a market (MTL) order to execute at the best available price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return self.place_order(
            account_no,
            symbol,
            side,
            quantity,
            price=0,
            order_type=OrderType.MTL,
            client_request_id=client_request_id,
        )

    def place_ato_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place an at-the-open (ATO) order matched at the opening auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return self.place_order(
            account_no,
            symbol,
            side,
            quantity,
            price=0,
            order_type=OrderType.ATO,
            client_request_id=client_request_id,
        )

    def place_atc_order(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        client_request_id: str | None = None,
    ) -> PlaceOrderResponse:
        """Place an at-the-close (ATC) order matched at the closing auction price.

        Args:
            account_no: Trading account number.
            symbol: Ticker symbol, e.g. "VNM".
            side: Order side (BUY or SELL).
            quantity: Number of shares to order.
            client_request_id: Optional idempotency key (<= 20 chars). Omit it to have the SDK
                               generate one. Re-sending a used key within the day is rejected
                               with ``DuplicateRequestError`` (HTTP 409); the SDK never retries
                               an order itself.

        Returns:
            The placed order response from the server.

        Raises:
            ValidationError: If a required field is missing.
            APIError: If the server rejects the request.
            AuthenticationError: If signing or authentication fails.
        """
        return self.place_order(
            account_no,
            symbol,
            side,
            quantity,
            price=0,
            order_type=OrderType.ATC,
            client_request_id=client_request_id,
        )

    def _modify_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
        price: PriceLike | None = None,
        quantity: int | None = None,
    ) -> ModifyOrderResponse:
        """Build, sign, and PUT a modify-order request, returning the parsed response."""
        req = _build_modify_order(
            account_no, order_id, client_request_id, price, quantity, self._rest.config
        )
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
        price: PriceLike,
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
        require_positive(to_price_decimal(price), "price")
        return self._modify_order(
            account_no=account_no, client_request_id=client_request_id, price=price
        )

    def modify_order_price_by_order_id(
        self,
        account_no: str,
        order_id: str,
        price: PriceLike,
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
        require_positive(to_price_decimal(price), "price")
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
        req = _build_cancel_order(account_no, order_id, client_request_id, self._rest.config)
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

    def place_batch_orders(self, orders: list[BatchPlaceOrderItem]) -> BatchOrderResponse:
        """Place a batch of orders in one signed request (``POST /order/batch``).

        At most ``Config.max_batch_orders`` orders (the server's default is 20).

        All orders are validated first and the server accepts or rejects the batch as a whole.
        ``batchRequestId`` is random and ``batchRequestTime`` is the current time; the request
        is signed over the whole body and never retried.

        Args:
            orders: One dict per order with the ``place_order`` arguments (``account_no``,
                    ``symbol``, ``side``, ``quantity``, ``price``, ``order_type`` and optionally
                    ``client_request_id``).

        Returns:
            ``results`` with one entry per order (``client_request_id``, ``order_id``,
            ``status``, ``success``, ``error_code``, ``error_message``).

        Raises:
            ValidationError: Empty batch, over ``Config.max_batch_orders`` orders, or a bad order.
            DuplicateRequestError: The batch id was already used today (HTTP 409).
            APIError: The server rejects the request (e.g. 400111, time outside the window).
        """
        request = _build_batch_place(orders, self._rest.config)
        content, sig = _sign_and_encode(request, self._rest.get_private_key())
        data = self._rest.post(
            EP_TRADING_ORDER_BATCH, content=content, headers={HEADER_SIGNATURE: sig}
        )
        return BatchOrderResponse.from_dict(data)

    def cancel_batch_orders(self, orders: list[BatchCancelOrderItem]) -> BatchOrderResponse:
        """Cancel a batch of orders in one signed request (``DELETE /order/batch``).

        At most ``Config.max_batch_orders`` orders (the server's default is 20).

        Args:
            orders: One dict per order: ``account_no`` and exactly one of ``order_id`` /
                    ``client_request_id``.

        Returns:
            ``results`` as for :meth:`place_batch_orders`, plus ``client_cancel_id`` per order.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
        """
        request = _build_batch_cancel(orders, self._rest.config)
        content, sig = _sign_and_encode(request, self._rest.get_private_key())
        data = self._rest.delete(
            EP_TRADING_ORDER_BATCH, content=content, headers={HEADER_SIGNATURE: sig}
        )
        return BatchOrderResponse.from_dict(data)

    def _get_max_buy_sell(
        self,
        account_no: str,
        symbol: str,
        price: PriceLike | None = None,
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
        price: PriceLike,
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
        type: FCOTypeLike | None = None,
        process_status: FCOStatusLike | list[FCOStatusLike] | None = None,
        symbol: str | None = None,
        side: OrderSide | str | None = None,
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
        """Get all FCO orders for a trading account.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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
        """Get FCO orders filtered by stock or derivative symbol.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
        return self._get_fco_list(
            account_no=account_no,
            symbol=symbol,
            page_index=page_index,
            page_size=page_size,
        )

    def get_fco_by_status(
        self,
        account_no: str,
        process_status: FCOStatusLike | list[FCOStatusLike],
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> FCOListResponse:
        """Get FCO orders filtered by processing status.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            process_status: FCO status to filter by: an ``FCOStatus`` member or its string
                            (``"WAIT"``, ``"TRI"``, ...); pass a list to match several.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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
        """Get FCO orders filtered by date range.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            from_date: Start of the date filter, ``"YYYY/MM/DD HH:MM:SS"`` (a bare date is
                       accepted).
            to_date: End of the date filter, same format; must not precede ``from_date``.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            A paginated ``FCOListResponse`` (iterable of ``FCOInfo``; see ``pages_count`` and
            ``items_count``).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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
        """Get a single FCO order by FCO ID.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.

        Returns:
            The ``FCOInfo``, or ``None`` when no such FCO exists for the account.

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
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

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            APIError: The server rejects the request.
        """
        require_non_empty(fco_id, "fcoId")
        params = FCOOrderBookRequest(
            fco_id=fco_id,
            page_index=page_index if page_index is not None else 1,
            page_size=page_size if page_size is not None else 10,
        ).to_dict()
        data = self._rest.get(EP_TRADING_FCO_ORDER_BOOK, params=params)
        return FCOOrderBookResponse.from_dict(data)

    def get_fco_status_history(self, fco_id: str) -> list[FCOStatusHistoryItem]:
        """Get the status transitions of a conditional (FCO) order.

        Args:
            fco_id: Id of the FCO.

        Returns:
            The recorded transitions (state, time, code, detail); empty when there are none.

        Raises:
            ValidationError: If ``fco_id`` is empty.
            APIError: If the server rejects the request.
        """
        require_non_empty(fco_id, "fcoId")
        params = FCOStatusHistoryRequest(fco_id=fco_id).to_dict()
        data = self._rest.get(EP_TRADING_FCO_STATUS_HISTORY, params=params)
        return FCOStatusHistoryItem.from_response(data)

    def _place_fco(
        self,
        params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams,
    ) -> FCOPlaceResponse:
        """Place a conditional (FCO) order."""
        _params = _build_fco_params(params, self._rest.config)
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
        price: PriceLike | OrderType,
        price_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a GTD order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return self._place_fco(params)

    def place_fco_stop(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_price: NumberLike,
        operator: FCOOperatorLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a stop order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            stop_price: Trigger price of the stop, in VND.
            operator: Comparison that fires the trigger, e.g. ``FCOOperator.GREATER_OR_EQUAL``
                      (fires when price >= ``stop_price``) or ``FCOOperator.LESSER_OR_EQUAL``.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
        params = StopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            price=OrderType.MTL,
            price_slip=0,
            quantity=quantity,
            stop_price=stop_price,
            operator=_operator(operator),
            from_date=from_date,
            to_date=to_date,
            code=code,
        )
        return self._place_fco(params)

    def place_fco_stop_limit(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: PriceLike,
        price_slip: NumberLike,
        stop_price: NumberLike,
        operator: FCOOperatorLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a stop order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            stop_price: Trigger price of the stop, in VND.
            operator: Comparison that fires the trigger, e.g. ``FCOOperator.GREATER_OR_EQUAL``
                      (fires when price >= ``stop_price``) or ``FCOOperator.LESSER_OR_EQUAL``.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
        params = StopParams(
            account_no=account_no,
            fco_type=FCOType.STOP_LIMIT,
            symbol=symbol,
            side=side,
            price=price,
            price_slip=price_slip,
            quantity=quantity,
            stop_price=stop_price,
            operator=_operator(operator),
            from_date=from_date,
            to_date=to_date,
            code=code,
        )
        return self._place_fco(params)

    def place_fco_trailing_stop(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: NumberLike,
        trailing_amount: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a stop order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            active_price: Price at which the trailing stop becomes active, in VND.
            trailing_amount: Distance in VND the price must retrace from its best level to fire
                             the stop.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
        params = TrailingStopParams(
            account_no=account_no,
            symbol=symbol,
            side=side,
            active_price=active_price,
            trailing_amount=trailing_amount,
            quantity=quantity,
            from_date=from_date,
            to_date=to_date,
            code=code,
        )
        return self._place_fco(params)

    def place_fco_trailing_stop_limit(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        active_price: NumberLike,
        trailing_amount: NumberLike,
        price_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a stop order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            active_price: Price at which the trailing stop becomes active, in VND.
            trailing_amount: Distance in VND the price must retrace from its best level to fire
                             the stop.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return self._place_fco(params)

    def place_fco_oco(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        tp_active_price: NumberLike,
        sl_active_price: NumberLike,
        tp_price: PriceLike | OrderType,
        sl_price: PriceLike | OrderType,
        tp_slip: NumberLike,
        sl_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place a OCO order.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            tp_active_price: Take-profit trigger price, in VND.
            sl_active_price: Stop-loss trigger price, in VND.
            tp_price: Order price once take-profit fires: a number, or an ``OrderType`` word.
            sl_price: Order price once stop-loss fires: a number, or an ``OrderType`` word.
            tp_slip: Slippage in VND allowed on the take-profit order.
            sl_slip: Slippage in VND allowed on the stop-loss order.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return self._place_fco(params)

    def place_fco_bull_bear(
        self,
        account_no: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: PriceLike,
        price_slip: NumberLike,
        tp_active_price: NumberLike,
        sl_active_price: NumberLike,
        tp_price: PriceLike | OrderType,
        sl_price: PriceLike | OrderType,
        tp_slip: NumberLike,
        sl_slip: NumberLike,
        from_date: str,
        to_date: str,
        code: str | None = None,
    ) -> FCOPlaceResponse:
        """Place fco bull bear.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            quantity: Number of shares/contracts; a positive integer.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            price_slip: Slippage in VND allowed on top of the price when the order is sent.
            tp_active_price: Take-profit trigger price, in VND.
            sl_active_price: Stop-loss trigger price, in VND.
            tp_price: Order price once take-profit fires: a number, or an ``OrderType`` word.
            sl_price: Order price once stop-loss fires: a number, or an ``OrderType`` word.
            tp_slip: Slippage in VND allowed on the take-profit order.
            sl_slip: Slippage in VND allowed on the stop-loss order.
            from_date: Start of the validity window, ``"YYYY/MM/DD HH:MM:SS"``.
            to_date: End of the validity window, ``"YYYY/MM/DD HH:MM:SS"``; at most 31 days
                     after ``from_date``.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is missing/invalid, or ``Config.private_key`` is not set
                (nothing is sent).
            APIError: The server rejects the request.
            DuplicateRequestError: The id was already used (HTTP 409).
        """
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
            code=code,
        )
        return self._place_fco(params)

    def cancel_fco(self, fco_id: str, code: str | None = None) -> FCOCancelResponse:
        """Cancel a FCO.

        Args:
            fco_id: Id of the conditional order to cancel.
            code: One-time code (OTP) when the account requires one for conditional orders;
                  omitted when empty.

        Returns:
            The cancelled FCO id.

        Raises:
            ValidationError: If ``fco_id`` is empty.
            APIError: If the server rejects the request.
        """
        require_non_empty(fco_id, "fcoId")
        config = self._rest.config
        params = FCOCancelRequest(
            fco_id=fco_id,
            device_id=get_device_id(),
            user_agent=config.user_agent,
            code=code,
        )
        content, sig = _sign_and_encode(params, self._rest.get_private_key())
        data = self._rest.delete(
            EP_TRADING_FCO_ORDER,
            content=content,
            headers={HEADER_SIGNATURE: sig},
        )
        return FCOCancelResponse.from_dict(data)
