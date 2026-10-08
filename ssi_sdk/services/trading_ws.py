"""EXPERIMENTAL: order entry and queries over the trading WebSocket (async and sync).

Not part of the ``Trading``/``Stream`` facades: the server side is not announced as released.
See ``ssi_sdk.transport.trading_ws`` for the protocol rules.

Scopes the token needs: ``tradingws:order:post`` / ``:put`` / ``:delete`` (place / amend /
cancel, batch), ``tradingws:fco:post`` / ``:delete`` / ``:get`` (conditional orders) and
``tradingws:position:get`` / ``:maxBuySell:get`` / ``:accountBalance:get`` /
``:ppmmrAccount:get`` / ``:orderBook:get`` (queries). A missing scope is refused with 403.
Rate limits: 50 commands per window for orders, 100 for queries; the response carries the
remaining quota (``client.rate_limit``) and the client waits for the reset when it hits zero.
"""

from __future__ import annotations

from typing import Any

from ssi_sdk.config import Config
from ssi_sdk.enums import FCOStatusLike, FCOTypeLike, OrderSide, OrderType
from ssi_sdk.exceptions import ValidationError
from ssi_sdk.models import (
    BatchCancelOrderItem,
    BatchPlaceOrderItem,
    BullBearParams,
    CancelOrderResponse,
    FCOCancelRequest,
    FCOCancelResponse,
    FCOOrderBookRequest,
    FCOPlaceResponse,
    GTDParams,
    ModifyOrderResponse,
    OCOParams,
    PlaceOrderResponse,
    PriceLike,
    StopParams,
    TrailingStopParams,
)
from ssi_sdk.services.trading import (
    _build_batch_cancel,
    _build_batch_place,
    _build_cancel_order,
    _build_fco_list,
    _build_fco_params,
    _build_modify_order,
    _build_place_order,
)
from ssi_sdk.transport.trading_ws import (
    AsyncTradingWSClient,
    TradingWSClient,
    TradingWSResponse,
)
from ssi_sdk.utils import (
    get_device_id,
    parse_date_arg,
    require_date_range,
    require_non_empty,
    require_non_negative,
    to_price_decimal,
)
from ssi_sdk.utils.topic import build_topic


def _account_topic(kind: str, account_no: str) -> str:
    """``order.<account>`` / ``portfolio.<account>``: the server refuses wildcards and accounts
    the token does not own, so an empty or ``*`` account is rejected before anything is sent."""
    require_non_empty(account_no, "accountNo")
    if "*" in account_no or "," in account_no:
        raise ValidationError("subscribe to one account at a time (no wildcard or list)")
    return build_topic(kind, account_no)


def _ws_params(params: dict[str, Any], client_id: str | None) -> dict[str, Any]:
    """Add ``clientId`` only when configured (an empty one is omitted, not sent)."""
    if client_id:
        params["clientId"] = client_id
    return params


def _as_dict(value: Any) -> dict:
    """A response ``result`` as a dict (anything else counts as empty)."""
    return value if isinstance(value, dict) else {}


class AsyncTradingWSService:
    """Order entry and queries over the trading WebSocket (async). EXPERIMENTAL.

    Builds the same validated payloads as the REST ``TradingService`` (device id from
    ``Config``, idempotency key, decimal prices) and sends them as signed commands. Order
    methods return the immediate ack (``orderStatus`` ``PD``); the real outcome arrives on the
    ``order.<account>`` event stream.
    """

    def __init__(self, client: AsyncTradingWSClient, config: Config):
        """Wrap a connected client; ``config`` supplies the device id and client id."""
        self._ws = client
        self._config = config

    @property
    def client(self) -> AsyncTradingWSClient:
        """The underlying socket client: set ``client.on_event`` to receive events and acks
        that carry no command id, and read ``client.rate_limit``."""
        return self._ws

    async def close(self) -> None:
        """Close the socket and wake any waiting request (call it when you are done)."""
        await self._ws.close()

    # -- generic -------------------------------------------------

    async def command(self, method: str, params: dict[str, Any]) -> TradingWSResponse:
        """Send any command and return its first response frame (no retry).

        Args:
            method: Server command name, e.g. ``"query.position"`` or ``"order.place"``.
            params: JSON-serializable command parameters (signed exactly as sent for state-
                    changing commands).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.
        """
        return await self._ws.request(method, params)

    # -- orders --------------------------------------------------

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
        """Place an order (``order.place``).

        ``client_request_id`` (<= 20 chars) is the idempotency key; omitted, one is generated.
        A reused key is rejected by the server (409). The command is never retried.

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
            order_type: Order type, e.g. ``OrderType.LO`` (limit), ``ATO``, ``ATC``, ``MP``.
            client_request_id: Idempotency key you chose (<= 20 characters). Give exactly one of
                               ``order_id`` / ``client_request_id`` when identifying an existing
                               order.

        Returns:
            The immediate ack (``order_id``, ``client_request_id``, ``status`` usually ``PD``);
            the outcome arrives on the order events.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        if price is not None:
            require_non_negative(to_price_decimal(price), "price")
        request = _build_place_order(
            account_no, symbol, side, quantity, price, order_type, self._config, client_request_id
        )
        response = await self._ws.request("order.place", request.to_dict())
        return PlaceOrderResponse.from_dict(_as_dict(response.result))

    async def amend_order(
        self,
        account_no: str,
        price: PriceLike | None = None,
        quantity: int | None = None,
        order_id: str | None = None,
        client_request_id: str | None = None,
    ) -> ModifyOrderResponse:
        """Change the price or the quantity (not both) of one order (``order.amend``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            quantity: Number of shares/contracts; a positive integer.
            order_id: Server order id. Give exactly one of ``order_id`` / ``client_request_id``.
            client_request_id: Idempotency key you chose (<= 20 characters). Give exactly one of
                               ``order_id`` / ``client_request_id`` when identifying an existing
                               order.

        Returns:
            The immediate ack with the order's ``order_id`` and ``status``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_modify_order(
            account_no, order_id, client_request_id, price, quantity, self._config
        )
        response = await self._ws.request("order.amend", request.to_dict())
        return ModifyOrderResponse.from_dict(_as_dict(response.result))

    async def cancel_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
    ) -> CancelOrderResponse:
        """Cancel one order identified by exactly one of ``order_id`` / ``client_request_id``.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            order_id: Server order id. Give exactly one of ``order_id`` / ``client_request_id``.
            client_request_id: Idempotency key you chose (<= 20 characters). Give exactly one of
                               ``order_id`` / ``client_request_id`` when identifying an existing
                               order.

        Returns:
            The immediate ack with the order's ``order_id`` and ``status``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_cancel_order(account_no, order_id, client_request_id, self._config)
        response = await self._ws.request("order.cancel", request.to_dict())
        return CancelOrderResponse.from_dict(_as_dict(response.result))

    async def batch_new_orders(self, orders: list[BatchPlaceOrderItem]) -> TradingWSResponse:
        """Place a batch of orders atomically (``order.batchNew``); same input as REST
        ``place_batch_orders``. Returns the ack: ``result.results`` lists
        ``clientRequestId``/``orderStatus``/``success``.

        Args:
            orders: Order items (see the item type); at most ``Config.max_batch_orders``
                (default 20), validated as a whole.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_batch_place(orders, self._config)
        return await self._ws.request("order.batchNew", request.to_dict())

    async def batch_cancel_orders(self, orders: list[BatchCancelOrderItem]) -> TradingWSResponse:
        """Cancel a batch of orders atomically (``order.batchCancel``); same input as REST
        ``cancel_batch_orders``.

        Args:
            orders: Order items (see the item type); at most ``Config.max_batch_orders``
                (default 20), validated as a whole.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_batch_cancel(orders, self._config)
        return await self._ws.request("order.batchCancel", request.to_dict())

    # -- FCO -----------------------------------------------------

    async def place_fco(
        self, params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams
    ) -> FCOPlaceResponse:
        """Place a conditional order (``fco.place``) from the same params classes as REST.

        Args:
            params: JSON-serializable command parameters (signed exactly as sent for state-
                    changing commands).

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        prepared = _build_fco_params(params, self._config)
        response = await self._ws.request("fco.place", prepared.to_dict())
        return FCOPlaceResponse.from_dict(_as_dict(response.result))

    async def cancel_fco(self, fco_id: str, code: str | None = None) -> FCOCancelResponse:
        """Cancel a conditional order (``fco.cancel``, scope ``tradingws:fco:delete``).

        Args:
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.
            code: One-time code (OTP) when the account requires one; omitted when empty.

        Returns:
            ``FCOCancelResponse`` carrying the cancelled ``fco_id``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(fco_id, "fcoId")
        request = FCOCancelRequest(
            fco_id=fco_id,
            device_id=get_device_id(),
            user_agent=self._config.user_agent,
            code=code,
        )
        response = await self._ws.request("fco.cancel", request.to_dict())
        return FCOCancelResponse.from_dict(_as_dict(response.result))

    async def list_fco(
        self,
        account_no: str,
        fco_id: str | None = None,
        type: FCOTypeLike | None = None,
        process_status: FCOStatusLike | None = None,
        symbol: str | None = None,
        side: OrderSide | str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> TradingWSResponse:
        """List conditional orders (``fco.list``), optionally filtered.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                ``8``).
            fco_id: Only this conditional order.
            type: Only this FCO type (``FCOType`` or its string, e.g. ``"oco"``).
            process_status: Only this status (``FCOStatus`` or string); one value, not a list.
            symbol: Only this ticker.
            side: Only ``OrderSide.BUY`` / ``OrderSide.SELL``.
            from_date: Start of the date filter, ``"YYYY/MM/DD HH:MM:SS"`` (a bare date works).
            to_date: End of the date filter, same format; must not precede ``from_date``.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            ``TradingWSResponse``; ``result`` holds the page (``data``, ``pagesCount``...).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        if isinstance(process_status, (list, tuple, set)):
            raise ValidationError("fco.list takes a single process_status, not a list")
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
        return await self._ws.request("fco.list", params)

    async def fco_order_book(self, fco_id: str) -> TradingWSResponse:
        """Execution log of one conditional order (``fco.orderbook``).

        Args:
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(fco_id, "fcoId")
        return await self._ws.request("fco.orderbook", FCOOrderBookRequest(fco_id=fco_id).to_dict())

    async def fco_status_history(self, fco_id: str) -> TradingWSResponse:
        """State transitions of one conditional order (``fco.statusHistory``, ``fco:get``).

        Args:
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(fco_id, "fcoId")
        return await self._ws.request("fco.statusHistory", {"fcoId": fco_id})

    async def subscribe_order_events(self, account_no: str) -> None:
        """Subscribe to ``order.<account>`` events (order status, fills) on this socket.

        Events arrive on the client's ``on_event`` hook
        as ``{"channel", "topic", "data"}`` frames (``data.eventType``: ``orderEvent`` /
        ``orderMatchEvent``). The server accepts only an account the token owns, so a
        wildcard is refused here instead of being sent to get ``Denied (account)``.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        await self._ws.subscribe("TRADING", [_account_topic("order", account_no)])

    async def unsubscribe_order_events(self, account_no: str) -> None:
        """Remove a subscription made with :meth:`subscribe_order_events`.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        await self._ws.unsubscribe("TRADING", [_account_topic("order", account_no)])

    async def subscribe_portfolio_events(self, account_no: str) -> None:
        """Subscribe to ``portfolio.<account>`` events (derivative position updates).

        Events arrive on ``on_event`` with ``data.eventType`` ``clientPortfolioEvent``.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        await self._ws.subscribe("TRADING", [_account_topic("portfolio", account_no)])

    async def unsubscribe_portfolio_events(self, account_no: str) -> None:
        """Remove a subscription made with :meth:`subscribe_portfolio_events`.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        await self._ws.unsubscribe("TRADING", [_account_topic("portfolio", account_no)])

    async def unsubscribe_all_events(self) -> None:
        """Drop every trading subscription of this socket (``UNSUBSCRIBE`` with no topics).

        Raises:
            WebSocketError: Not connected.
        """
        await self._ws.unsubscribe("TRADING", [])

    async def query_position(
        self, account_no: str, query_summary: bool = True
    ) -> TradingWSResponse:
        """Positions of an account (``query.position``, scope ``tradingws:position:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            query_summary: ``True`` for the account summary too (sent as a JSON boolean).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        params = _ws_params(
            {"accountNo": account_no, "querySummary": bool(query_summary)}, self._config.client_id
        )
        return await self._ws.request("query.position", params)

    async def query_max_buy_sell(
        self, account_no: str, symbol: str, price: PriceLike | None = None
    ) -> TradingWSResponse:
        """Maximum buy/sell quantity (``query.maxBuySell``, scope ``tradingws:maxBuySell:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine); sent
                   as a JSON number. Omit it to let the server use its reference price.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        require_non_empty(symbol, "symbol")
        params: dict[str, Any] = {"accountNo": account_no, "symbol": symbol.upper()}
        if price is not None:
            params["price"] = require_non_negative(to_price_decimal(price), "price")
        return await self._ws.request("query.maxBuySell", params)

    async def query_account_balance(self, account_no: str) -> TradingWSResponse:
        """Cash balance (``query.accountBalance``, scope ``tradingws:accountBalance:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        params = _ws_params({"accountNo": account_no}, self._config.client_id)
        return await self._ws.request("query.accountBalance", params)

    async def query_ppmmr_account(self, account_no: str) -> TradingWSResponse:
        """Purchasing power (``query.ppmmrAccount``, scope ``tradingws:ppmmrAccount:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        return await self._ws.request("query.ppmmrAccount", {"accountNo": account_no})

    async def query_order_book(
        self,
        account_no: str,
        from_date: str | None = None,
        to_date: str | None = None,
        symbol: str | None = None,
        order_status: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> TradingWSResponse:
        """Order book of an account (``query.orderBook``, scope ``tradingws:orderBook:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            from_date: Start of the range, ``"YYYY/MM/DD"``; optional.
            to_date: End of the range, ``"YYYY/MM/DD"``; optional, not before ``from_date``.
            symbol: Only this ticker.
            order_status: Only this order status (``OrderStatus`` value, e.g. ``"FF"``).
            page_index: 1-based page number (server default applies when omitted).
            page_size: Rows per page (server default applies when omitted).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        params: dict[str, Any] = {"accountNo": account_no}
        if from_date is not None and to_date is not None:
            require_date_range(from_date, to_date)
        for key, value in (("from", from_date), ("to", to_date)):
            if value is not None:
                parse_date_arg(value, key)
                params[key] = value
        for name, extra in (
            ("symbol", symbol),
            ("orderStatus", getattr(order_status, "value", order_status)),
            ("pageIndex", page_index),
            ("pageSize", page_size),
        ):
            if extra is not None:
                params[name] = extra
        return await self._ws.request("query.orderBook", params)

class TradingWSService:
    """Order entry and queries over the trading WebSocket (sync). EXPERIMENTAL.

    Builds the same validated payloads as the REST ``TradingService`` (device id from
    ``Config``, idempotency key, decimal prices) and sends them as signed commands. Order
    methods return the immediate ack (``orderStatus`` ``PD``); the real outcome arrives on the
    ``order.<account>`` event stream.
    """

    def __init__(self, client: TradingWSClient, config: Config):
        """Wrap a connected client; ``config`` supplies the device id and client id."""
        self._ws = client
        self._config = config

    @property
    def client(self) -> TradingWSClient:
        """The underlying socket client: set ``client.on_event`` to receive events and acks
        that carry no command id, and read ``client.rate_limit``."""
        return self._ws

    def close(self) -> None:
        """Close the socket and wake any waiting request (call it when you are done)."""
        self._ws.close()

    # -- generic -------------------------------------------------

    def command(self, method: str, params: dict[str, Any]) -> TradingWSResponse:
        """Send any command and return its first response frame (no retry).

        Args:
            method: Server command name, e.g. ``"query.position"`` or ``"order.place"``.
            params: JSON-serializable command parameters (signed exactly as sent for state-
                    changing commands).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.
        """
        return self._ws.request(method, params)

    # -- orders --------------------------------------------------

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
        """Place an order (``order.place``).

        ``client_request_id`` (<= 20 chars) is the idempotency key; omitted, one is generated.
        A reused key is rejected by the server (409). The command is never retried.

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
            order_type: Order type, e.g. ``OrderType.LO`` (limit), ``ATO``, ``ATC``, ``MP``.
            client_request_id: Idempotency key you chose (<= 20 characters). Give exactly one of
                               ``order_id`` / ``client_request_id`` when identifying an existing
                               order.

        Returns:
            The immediate ack (``order_id``, ``client_request_id``, ``status`` usually ``PD``);
            the outcome arrives on the order events.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        if price is not None:
            require_non_negative(to_price_decimal(price), "price")
        request = _build_place_order(
            account_no, symbol, side, quantity, price, order_type, self._config, client_request_id
        )
        response = self._ws.request("order.place", request.to_dict())
        return PlaceOrderResponse.from_dict(_as_dict(response.result))

    def amend_order(
        self,
        account_no: str,
        price: PriceLike | None = None,
        quantity: int | None = None,
        order_id: str | None = None,
        client_request_id: str | None = None,
    ) -> ModifyOrderResponse:
        """Change the price or the quantity (not both) of one order (``order.amend``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            price: Order price in VND as a number or decimal string (``Decimal`` is fine). Pass
                   an ``OrderType`` (``MP``, ``MTL``, ...) for a market-priced leg; the slip is
                   then ignored.
            quantity: Number of shares/contracts; a positive integer.
            order_id: Server order id. Give exactly one of ``order_id`` / ``client_request_id``.
            client_request_id: Idempotency key you chose (<= 20 characters). Give exactly one of
                               ``order_id`` / ``client_request_id`` when identifying an existing
                               order.

        Returns:
            The immediate ack with the order's ``order_id`` and ``status``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_modify_order(
            account_no, order_id, client_request_id, price, quantity, self._config
        )
        response = self._ws.request("order.amend", request.to_dict())
        return ModifyOrderResponse.from_dict(_as_dict(response.result))

    def cancel_order(
        self,
        account_no: str,
        order_id: str | None = None,
        client_request_id: str | None = None,
    ) -> CancelOrderResponse:
        """Cancel one order identified by exactly one of ``order_id`` / ``client_request_id``.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            order_id: Server order id. Give exactly one of ``order_id`` / ``client_request_id``.
            client_request_id: Idempotency key you chose (<= 20 characters). Give exactly one of
                               ``order_id`` / ``client_request_id`` when identifying an existing
                               order.

        Returns:
            The immediate ack with the order's ``order_id`` and ``status``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_cancel_order(account_no, order_id, client_request_id, self._config)
        response = self._ws.request("order.cancel", request.to_dict())
        return CancelOrderResponse.from_dict(_as_dict(response.result))

    def batch_new_orders(self, orders: list[BatchPlaceOrderItem]) -> TradingWSResponse:
        """Place a batch of orders atomically (``order.batchNew``); same input as REST
        ``place_batch_orders``. Returns the ack: ``result.results`` lists
        ``clientRequestId``/``orderStatus``/``success``.

        Args:
            orders: Order items (see the item type); at most ``Config.max_batch_orders``
                (default 20), validated as a whole.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_batch_place(orders, self._config)
        return self._ws.request("order.batchNew", request.to_dict())

    def batch_cancel_orders(self, orders: list[BatchCancelOrderItem]) -> TradingWSResponse:
        """Cancel a batch of orders atomically (``order.batchCancel``); same input as REST
        ``cancel_batch_orders``.

        Args:
            orders: Order items (see the item type); at most ``Config.max_batch_orders``
                (default 20), validated as a whole.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        request = _build_batch_cancel(orders, self._config)
        return self._ws.request("order.batchCancel", request.to_dict())

    # -- FCO -----------------------------------------------------

    def place_fco(
        self, params: GTDParams | StopParams | TrailingStopParams | OCOParams | BullBearParams
    ) -> FCOPlaceResponse:
        """Place a conditional order (``fco.place``) from the same params classes as REST.

        Args:
            params: JSON-serializable command parameters (signed exactly as sent for state-
                    changing commands).

        Returns:
            ``FCOPlaceResponse`` carrying the new ``fco_id``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        prepared = _build_fco_params(params, self._config)
        response = self._ws.request("fco.place", prepared.to_dict())
        return FCOPlaceResponse.from_dict(_as_dict(response.result))

    def cancel_fco(self, fco_id: str, code: str | None = None) -> FCOCancelResponse:
        """Cancel a conditional order (``fco.cancel``, scope ``tradingws:fco:delete``).

        Args:
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.
            code: One-time code (OTP) when the account requires one; omitted when empty.

        Returns:
            ``FCOCancelResponse`` carrying the cancelled ``fco_id``.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(fco_id, "fcoId")
        request = FCOCancelRequest(
            fco_id=fco_id,
            device_id=get_device_id(),
            user_agent=self._config.user_agent,
            code=code,
        )
        response = self._ws.request("fco.cancel", request.to_dict())
        return FCOCancelResponse.from_dict(_as_dict(response.result))

    def list_fco(
        self,
        account_no: str,
        fco_id: str | None = None,
        type: FCOTypeLike | None = None,
        process_status: FCOStatusLike | None = None,
        symbol: str | None = None,
        side: OrderSide | str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> TradingWSResponse:
        """List conditional orders (``fco.list``), optionally filtered.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                ``8``).
            fco_id: Only this conditional order.
            type: Only this FCO type (``FCOType`` or its string, e.g. ``"oco"``).
            process_status: Only this status (``FCOStatus`` or string); one value, not a list.
            symbol: Only this ticker.
            side: Only ``OrderSide.BUY`` / ``OrderSide.SELL``.
            from_date: Start of the date filter, ``"YYYY/MM/DD HH:MM:SS"`` (a bare date works).
            to_date: End of the date filter, same format; must not precede ``from_date``.
            page_index: 1-based page number (server default 1).
            page_size: Rows per page (server default 10).

        Returns:
            ``TradingWSResponse``; ``result`` holds the page (``data``, ``pagesCount``...).

        Raises:
            ValidationError: A filter is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        if isinstance(process_status, (list, tuple, set)):
            raise ValidationError("fco.list takes a single process_status, not a list")
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
        return self._ws.request("fco.list", params)

    def fco_order_book(self, fco_id: str) -> TradingWSResponse:
        """Execution log of one conditional order (``fco.orderbook``).

        Args:
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(fco_id, "fcoId")
        return self._ws.request("fco.orderbook", FCOOrderBookRequest(fco_id=fco_id).to_dict())

    def fco_status_history(self, fco_id: str) -> TradingWSResponse:
        """State transitions of one conditional order (``fco.statusHistory``, ``fco:get``).

        Args:
            fco_id: Id of the conditional order, as returned by ``place_fco_*``.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(fco_id, "fcoId")
        return self._ws.request("fco.statusHistory", {"fcoId": fco_id})

    def subscribe_order_events(self, account_no: str) -> None:
        """Subscribe to ``order.<account>`` events (order status, fills) on this socket.

        Events arrive on the client's ``on_event`` hook
        as ``{"channel", "topic", "data"}`` frames (``data.eventType``: ``orderEvent`` /
        ``orderMatchEvent``). The server accepts only an account the token owns, so a
        wildcard is refused here instead of being sent to get ``Denied (account)``.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        self._ws.subscribe("TRADING", [_account_topic("order", account_no)])

    def unsubscribe_order_events(self, account_no: str) -> None:
        """Remove a subscription made with :meth:`subscribe_order_events`.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        self._ws.unsubscribe("TRADING", [_account_topic("order", account_no)])

    def subscribe_portfolio_events(self, account_no: str) -> None:
        """Subscribe to ``portfolio.<account>`` events (derivative position updates).

        Events arrive on ``on_event`` with ``data.eventType`` ``clientPortfolioEvent``.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        self._ws.subscribe("TRADING", [_account_topic("portfolio", account_no)])

    def unsubscribe_portfolio_events(self, account_no: str) -> None:
        """Remove a subscription made with :meth:`subscribe_portfolio_events`.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Raises:
            ValidationError: ``account_no`` is empty or ``"*"`` (nothing is sent).
            WebSocketError: Not connected.
        """
        self._ws.unsubscribe("TRADING", [_account_topic("portfolio", account_no)])

    def unsubscribe_all_events(self) -> None:
        """Drop every trading subscription of this socket (``UNSUBSCRIBE`` with no topics).

        Raises:
            WebSocketError: Not connected.
        """
        self._ws.unsubscribe("TRADING", [])

    def query_position(
        self, account_no: str, query_summary: bool = True
    ) -> TradingWSResponse:
        """Positions of an account (``query.position``, scope ``tradingws:position:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            query_summary: ``True`` for the account summary too (sent as a JSON boolean).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        params = _ws_params(
            {"accountNo": account_no, "querySummary": bool(query_summary)}, self._config.client_id
        )
        return self._ws.request("query.position", params)

    def query_max_buy_sell(
        self, account_no: str, symbol: str, price: PriceLike | None = None
    ) -> TradingWSResponse:
        """Maximum buy/sell quantity (``query.maxBuySell``, scope ``tradingws:maxBuySell:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            symbol: Ticker symbol, e.g. ``"SSI"``, or a derivative contract such as
                    ``"VN30F2606"``.
            price: Order price in VND as a number or decimal string (``Decimal`` is fine); sent
                   as a JSON number. Omit it to let the server use its reference price.

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        require_non_empty(symbol, "symbol")
        params: dict[str, Any] = {"accountNo": account_no, "symbol": symbol.upper()}
        if price is not None:
            params["price"] = require_non_negative(to_price_decimal(price), "price")
        return self._ws.request("query.maxBuySell", params)

    def query_account_balance(self, account_no: str) -> TradingWSResponse:
        """Cash balance (``query.accountBalance``, scope ``tradingws:accountBalance:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        params = _ws_params({"accountNo": account_no}, self._config.client_id)
        return self._ws.request("query.accountBalance", params)

    def query_ppmmr_account(self, account_no: str) -> TradingWSResponse:
        """Purchasing power (``query.ppmmrAccount``, scope ``tradingws:ppmmrAccount:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        return self._ws.request("query.ppmmrAccount", {"accountNo": account_no})

    def query_order_book(
        self,
        account_no: str,
        from_date: str | None = None,
        to_date: str | None = None,
        symbol: str | None = None,
        order_status: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> TradingWSResponse:
        """Order book of an account (``query.orderBook``, scope ``tradingws:orderBook:get``).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
            from_date: Start of the range, ``"YYYY/MM/DD"``; optional.
            to_date: End of the range, ``"YYYY/MM/DD"``; optional, not before ``from_date``.
            symbol: Only this ticker.
            order_status: Only this order status (``OrderStatus`` value, e.g. ``"FF"``).
            page_index: 1-based page number (server default applies when omitted).
            page_size: Rows per page (server default applies when omitted).

        Returns:
            ``TradingWSResponse`` (``status``, ``result``, ``rate_limit``) of the first response
            frame.

        Raises:
            ValidationError: A field is invalid (nothing is sent).
            TradingWSError: The server answers with an error frame.
            WebSocketError: Not connected, timed out (never retried) or the connection closed.
        """
        require_non_empty(account_no, "accountNo")
        params: dict[str, Any] = {"accountNo": account_no}
        if from_date is not None and to_date is not None:
            require_date_range(from_date, to_date)
        for key, value in (("from", from_date), ("to", to_date)):
            if value is not None:
                parse_date_arg(value, key)
                params[key] = value
        for name, extra in (
            ("symbol", symbol),
            ("orderStatus", getattr(order_status, "value", order_status)),
            ("pageIndex", page_index),
            ("pageSize", page_size),
        ):
            if extra is not None:
                params[name] = extra
        return self._ws.request("query.orderBook", params)
