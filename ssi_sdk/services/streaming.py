"""
Module: ssi_sdk.services.streaming
Provides the StreamingService class for real-time market data and trading updates via WebSocket.
The StreamingService allows subscribing to various channels
(trade, quote, order status, portfolio, etc.)
and handles incoming messages with user-defined callbacks.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

from ssi_sdk.constant import TOPIC_MARKET_FLAG, WS_ROUTE_ACK, WS_ROUTE_LIST_SUBSCRIPTION
from ssi_sdk.enums import (
    Board,
    DataTopic,
    StreamingChannel,
    StreamingMethod,
    StreamingType,
    Timeframe,
)
from ssi_sdk.exceptions import WebSocketError
from ssi_sdk.models import (
    DataMessage,
    FCOOrderUpdateMessage,
    ForeignRoomMessage,
    HeartbeatMessage,
    IndexSummaryMessage,
    IndexTickMessage,
    MarketDataMessage,
    MarketFlagMessage,
    MarketStatusMessage,
    OddLotMessage,
    OrderMatchMessage,
    OrderStatusMessage,
    PortfolioMessage,
    PutMessage,
    QuoteMessage,
    RequestMessage,
    TradeMessage,
    TradingMessage,
)
from ssi_sdk.models.streaming import IntervalMessage
from ssi_sdk.transport.dispatch import split_subscriptions
from ssi_sdk.transport.reconnect import ConnectionEvent
from ssi_sdk.transport.websocket_client import AsyncWebSocketClient, WebSocketClient
from ssi_sdk.utils.topic import StreamInterval, build_topic, build_topics

logger = logging.getLogger("ssi_sdk.services.streaming")


# ---------------------------------------------------------------------------
# Shared helpers (used by both AsyncStreamingService and StreamingService)
# ---------------------------------------------------------------------------


def _payload(msg: dict) -> dict:
    """The ``data`` object of a frame; anything that is not an object counts as empty."""
    data = msg.get("data")
    return data if isinstance(data, dict) else {}


def _parse_data_message(msg: dict) -> Any:
    """Deserialise a DATA-channel frame into its message model by topic.

    A frame whose topic this SDK has no model for (including acks) is returned as the raw dict.
    """

    topic = msg.get("topic")
    topic = topic if isinstance(topic, str) else ""
    data = _payload(msg)
    logger.debug(f"DATA RAW: {msg}")
    # The server upper-cases the part after the type (``market.FLAG``, ``trade.SSI``), so the
    # type is matched without regard to case.
    kind = topic.lower()
    if kind.startswith("trade.index."):
        # The index itself: ticks have their own shape (IndexData); candles keep the interval one.
        if kind.endswith(("@1m", "@5m")):
            return IntervalMessage.from_dict(data)
        return IndexTickMessage.from_dict(data)
    if kind.startswith(DataTopic.TRADE.value):
        if kind.endswith(("@1m", "@5m")):
            return IntervalMessage.from_dict(data)
        return TradeMessage.from_dict(data)
    if kind.startswith(DataTopic.QUOTE.value):
        return QuoteMessage.from_dict(data)
    if kind.startswith(DataTopic.ROOM.value):
        return ForeignRoomMessage.from_dict(data)
    if kind == TOPIC_MARKET_FLAG:
        return MarketFlagMessage.from_dict(data)
    if kind.startswith(DataTopic.INDEX_SUMMARY.value):
        return IndexSummaryMessage.from_dict(data, topic)
    if kind.startswith(DataTopic.MARKET.value):
        # ``market.<symbol>`` carries master data (s/b/t/ce/fl/ref); the legacy
        # status shape is kept for payloads that look like it.
        if any(key in data for key in ("s", "ce", "fl", "ref")):
            return MarketDataMessage.from_dict(data)
        return MarketStatusMessage.from_dict(data)
    if kind.startswith(DataTopic.PUT.value):
        return PutMessage.from_dict(data)
    if kind.startswith(DataTopic.ODD_LOT.value):
        return OddLotMessage.from_dict(data)
    return msg


def _parse_trading_message(msg: dict) -> Any:
    """Deserialise a TRADING-channel frame into its message model.

    The model is chosen by ``data.eventType``: ``orderEvent`` -> ``OrderStatusMessage``,
    ``orderMatchEvent`` -> ``OrderMatchMessage``, ``clientPortfolioEvent`` ->
    ``PortfolioMessage``. With no ``eventType`` the topic decides (``order.*`` /
    ``portfolio.*``); an event type this SDK does not know is passed on as the raw dict.
    """

    topic = msg.get("topic")
    topic = topic if isinstance(topic, str) else ""
    data = _payload(msg)
    event = data.get("eventType")
    if event == "fcoEvent":
        return FCOOrderUpdateMessage.from_dict(data)
    if event == StreamingType.ORDER_MATCH.value:
        return OrderMatchMessage.from_dict(data)
    if event == StreamingType.PORTFOLIO.value:
        return PortfolioMessage.from_dict(data)
    if event == StreamingType.ORDER.value:
        return OrderStatusMessage.from_dict(data)
    if event in (None, ""):
        if topic.startswith("order."):
            return OrderStatusMessage.from_dict(data)
        if topic.startswith("portfolio."):
            return PortfolioMessage.from_dict(data)
    return msg


def _wrap_data_callback(callback: Callable) -> Callable:
    """Wrap a user callback to deserialise DATA-channel messages by topic."""

    def _wrap(msg: dict) -> Any:
        return callback(_parse_data_message(msg))

    return _wrap


def _wrap_trading_callback(callback: Callable) -> Callable:
    """Wrap a user callback to deserialise TRADING-channel messages."""

    def _wrap(msg: dict) -> Any:
        return callback(_parse_trading_message(msg))

    return _wrap


def _build_subscribe_request(
    method: StreamingMethod,
    channel: StreamingChannel,
    topic_prefix: str,
    symbols: list[str],
) -> RequestMessage:
    """Build a subscribe/unsubscribe RequestMessage for the given symbols.

    Topics are validated against what the server accepts (see ``utils.topic``).
    """
    return RequestMessage(
        method=method, channel=channel, topics=build_topics(topic_prefix, symbols)
    )


def _build_ohlcv_request(
    method: StreamingMethod,
    symbols: list[str],
    interval: Timeframe | StreamInterval,
    topic_type: str = "trade",
) -> RequestMessage:
    """Build a subscribe/unsubscribe RequestMessage for interval (candle) topics.

    The stream serves only ``tick``, ``1m`` and ``5m``; anything else is rejected here
    instead of being silently ignored by the server.
    """
    return RequestMessage(
        method=method,
        channel=StreamingChannel.DATA,
        topics=build_topics(topic_type, symbols, interval),
    )


def _build_data_request(
    method: StreamingMethod, topic_type: str, symbols: list[str]
) -> RequestMessage:
    """Build a DATA-channel request for ``topic_type`` over the given codes."""
    return _build_subscribe_request(method, StreamingChannel.DATA, topic_type, symbols)


def _build_market_flag_request(method: StreamingMethod) -> RequestMessage:
    """Build the (un)subscribe request for the all-boards ``market.flag`` topic."""
    return RequestMessage(
        method=method, channel=StreamingChannel.DATA, topics=[TOPIC_MARKET_FLAG]
    )


def _build_trading_request(
    method: StreamingMethod, topic_type: str, account_no: str
) -> RequestMessage:
    """Build a TRADING-channel request for ``order.<account>`` / ``portfolio.<account>``."""
    return RequestMessage(
        method=method,
        channel=StreamingChannel.TRADING,
        topics=[build_topic(topic_type, account_no)],
    )


def _build_list_subscription_request() -> dict:
    """Build the ``LIST_SUBSCRIPTION`` request; it takes no channel and no topics."""
    return {"method": StreamingMethod.LIST_SUBSCRIPTION.value}


# Typed callbacks: name -> (channel, message class). Setting one subscribes nothing by itself;
# it only chooses where messages of that class are delivered. ``on_data`` / ``on_trading`` keep
# receiving every message of their channel, so existing code is unaffected.
_TYPED_CALLBACKS = {
    "market_flag": ("data", MarketFlagMessage),
    "index_summary": ("data", IndexSummaryMessage),
    "order": ("trading", OrderStatusMessage),
    "order_match": ("trading", OrderMatchMessage),
    "portfolio": ("trading", PortfolioMessage),
}


def _typed_targets(typed: dict, channel: str, message: Any) -> list[Callable]:
    """Typed callbacks (set) that want ``message`` on ``channel``."""
    return [
        typed[key]
        for key, (chan, cls) in _TYPED_CALLBACKS.items()
        if chan == channel and isinstance(message, cls) and typed.get(key) is not None
    ]


class _CallbackProperties:
    """Typed-callback and connection-state properties shared by the sync and async services.

    Written out one by one (not generated) so IDEs show each name, its callback signature and
    its description.
    """

    _typed: dict[str, Callable | None]
    _ws: Any

    def _refresh_handlers(self) -> None:
        raise NotImplementedError

    @property
    def on_market_flag(self) -> Callable[[MarketFlagMessage], Any] | None:
        """Callback for ``MarketFlagMessage`` (session flags: ATO/LO/ATC...).

        Needs ``subscribe_market_flag()`` (alias ``subscribe_session_flag``). ``on_data`` still
        receives these messages too.
        """
        return self._typed.get("market_flag")

    @on_market_flag.setter
    def on_market_flag(self, callback: Callable[[MarketFlagMessage], Any] | None) -> None:
        self._typed["market_flag"] = callback
        self._refresh_handlers()

    @property
    def on_index_summary(self) -> Callable[[IndexSummaryMessage], Any] | None:
        """Callback for ``IndexSummaryMessage`` (full index data from ``indexsummary.<code>``).

        Needs ``subscribe_index_summary(["VN30"])``. ``on_data`` still receives these too.
        """
        return self._typed.get("index_summary")

    @on_index_summary.setter
    def on_index_summary(self, callback: Callable[[IndexSummaryMessage], Any] | None) -> None:
        self._typed["index_summary"] = callback
        self._refresh_handlers()

    @property
    def on_order(self) -> Callable[[OrderStatusMessage], Any] | None:
        """Callback for ``OrderStatusMessage`` (``orderEvent``: an order changed status).

        Needs ``subscribe_order_status(account_no)`` (alias ``subscribe_orders``).
        """
        return self._typed.get("order")

    @on_order.setter
    def on_order(self, callback: Callable[[OrderStatusMessage], Any] | None) -> None:
        self._typed["order"] = callback
        self._refresh_handlers()

    @property
    def on_order_match(self) -> Callable[[OrderMatchMessage], Any] | None:
        """Callback for ``OrderMatchMessage`` (``orderMatchEvent``: a fill of your order).

        Needs ``subscribe_order_status(account_no)``; fills arrive on the same topic as status.
        """
        return self._typed.get("order_match")

    @on_order_match.setter
    def on_order_match(self, callback: Callable[[OrderMatchMessage], Any] | None) -> None:
        self._typed["order_match"] = callback
        self._refresh_handlers()

    @property
    def on_portfolio(self) -> Callable[[PortfolioMessage], Any] | None:
        """Callback for ``PortfolioMessage`` (derivative position updates).

        Needs ``subscribe_portfolio(account_no)``; only derivative accounts produce events.
        """
        return self._typed.get("portfolio")

    @on_portfolio.setter
    def on_portfolio(self, callback: Callable[[PortfolioMessage], Any] | None) -> None:
        self._typed["portfolio"] = callback
        self._refresh_handlers()

    @property
    def is_connected(self) -> bool:
        """Whether the socket is currently open."""
        return bool(self._ws.is_connected)

    @property
    def last_error(self) -> Exception | None:
        """The error that ended the connection for good (``None`` while healthy)."""
        return getattr(self._ws, "last_error", None)

    @property
    def reconnect_count(self) -> int:
        """How many times the socket was re-opened after a drop."""
        return int(getattr(self._ws, "reconnect_count", 0))

    @property
    def on_connection(self) -> Callable[[ConnectionEvent], Any] | None:
        """Callback ``f(ConnectionEvent)`` for connected / reconnected / disconnected / failed.

        It runs on the SDK's own thread (sync) or task (async): keep it short.
        """
        return getattr(self._ws, "on_state", None)

    @on_connection.setter
    def on_connection(self, callback: Callable[[ConnectionEvent], Any] | None) -> None:
        self._ws.on_state = callback


# ---------------------------------------------------------------------------
# Async service
# ---------------------------------------------------------------------------


class AsyncStreamingService(_CallbackProperties):
    """Unified real-time streaming via a single WebSocket connection.

    Market data channels: trade, quote, market-status, foreign-room, put, oddlot.
    Portfolio channels: order-status, portfolio.
    """

    def __init__(self, ws_client: AsyncWebSocketClient):
        """Initialise the service with an async WebSocket client."""
        self._ws = ws_client
        self._on_data_callbacks: Callable[[DataMessage], Any] | None = None
        self._on_trading_callbacks: Callable[[TradingMessage], Any] | None = None
        self._on_heartbeat_callbacks: Callable[[HeartbeatMessage], Any] | None = None
        self._typed: dict[str, Callable | None] = {}
        self._ping_task: asyncio.Task | None = None

    @property
    def on_data(self) -> Callable[[DataMessage], Any] | None:
        """Get the current callback for market data messages.

        Returns:
            The current market data callback, or None if not set.
        """
        return self._on_data_callbacks

    @on_data.setter
    def on_data(self, callback: Callable[[DataMessage], Any] | None) -> None:
        """Set a callback for market data messages.

        The callback will be invoked with the raw message dict whenever a new
        market data message is received on the DATA channel.

        Args:
            callback: Callback invoked with each market data message, or None to clear.
        """
        self._on_data_callbacks = callback
        self._refresh_handlers()

    @property
    def on_trading(self) -> Callable[[TradingMessage], Any] | None:
        """Get the current callback for trading messages.

        Returns:
            The current trading callback, or None if not set.
        """
        return self._on_trading_callbacks

    @on_trading.setter
    def on_trading(
        self, callback: Callable[[TradingMessage], Any] | None
    ) -> None:
        """Set a callback for trading messages.

        The callback will be invoked with an OrderStatusMessage or PortfolioMessage
        depending on the topic, whenever a new message is received on the TRADING channel.

        Args:
            callback: Callback invoked with each trading message, or None to clear.
        """
        self._on_trading_callbacks = callback
        self._refresh_handlers()

    @property
    def on_heartbeat(self) -> Callable[[HeartbeatMessage], Any] | None:
        """Get the current callback for heartbeat messages.

        Returns:
            The current heartbeat callback, or None if not set.
        """
        return self._on_heartbeat_callbacks

    @on_heartbeat.setter
    def on_heartbeat(self, callback: Callable[[HeartbeatMessage], Any] | None) -> None:
        """Set a callback for heartbeat messages.

        The callback will be invoked with a HeartbeatMessage whenever a new
        heartbeat message is received on the HEARTBEAT channel.

        Args:
            callback: Callback invoked with each heartbeat message, or None to clear.
        """
        self._on_heartbeat_callbacks = callback
        self._ws.on(
            StreamingChannel.HEARTBEAT.value,
            (lambda msg: callback(HeartbeatMessage.from_dict(msg)))
            if callback is not None
            else None,
        )

    def _deliver(self, callbacks: list[Callable], message: Any) -> Any:
        """Call each callback with ``message``; a failing one must not starve the others.

        Returns a coroutine only when some callback was async (the socket client awaits it).
        """
        pending = []
        for callback in callbacks:
            try:
                result = callback(message)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error in a streaming callback")
                continue
            if inspect.isawaitable(result):
                pending.append(result)
        return self._await_all(pending) if pending else None

    async def _await_all(self, pending: list) -> None:
        for result in pending:
            try:
                await result
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error in an async streaming callback")

    def _handle_data(self, msg: dict) -> Any:
        message = _parse_data_message(msg)
        targets = [cb for cb in [self._on_data_callbacks] if cb is not None]
        targets += _typed_targets(self._typed, "data", message)
        return self._deliver(targets, message)

    def _handle_trading(self, msg: dict) -> Any:
        message = _parse_trading_message(msg)
        targets = [cb for cb in [self._on_trading_callbacks] if cb is not None]
        targets += _typed_targets(self._typed, "trading", message)
        return self._deliver(targets, message)

    def _refresh_handlers(self) -> None:
        """Install (or clear) the one handler per channel from the callbacks currently set."""
        wants_data = self._on_data_callbacks is not None or any(
            self._typed.get(k) for k, (chan, _) in _TYPED_CALLBACKS.items() if chan == "data"
        )
        wants_trading = self._on_trading_callbacks is not None or any(
            self._typed.get(k) for k, (chan, _) in _TYPED_CALLBACKS.items() if chan == "trading"
        )
        self._ws.on(StreamingChannel.DATA.value, self._handle_data if wants_data else None)
        self._ws.on(
            StreamingChannel.TRADING.value, self._handle_trading if wants_trading else None
        )


    async def _subscribe(
        self,
        request: RequestMessage,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Helper to subscribe to a channel with an optional callback."""
        if on_response is not None:
            # Acknowledgements have their own route: registering on the request's channel
            # would replace the user's data/trading handler.
            self._ws.on(WS_ROUTE_ACK, on_response)
        await self._ws.send(request.to_dict())

    async def ping(
        self,
        on_response: Callable[[dict], Any] | None = None,
        interval: float | None = None,
    ) -> None:
        """Send a ping to the WebSocket server.

        Args:
            on_response: Optional callback for the ping response.
            interval: If provided, send a ping every *interval* seconds in the background.
                      Calling ping() again cancels the previous loop. Pass ``interval=None`` to
                      send a single ping.
        """

        async def _send_once() -> None:
            logger.debug("Sending ping to WebSocket server")
            await self._subscribe(
                RequestMessage(
                    method=StreamingMethod.PING_PONG,
                    channel=StreamingChannel.HEARTBEAT,
                ),
                on_response,
            )
            logger.debug("Ping sent to WebSocket server")

        if interval is None:
            await _send_once()
            return

        # Cancel any existing ping loop
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()

        async def _ping_loop() -> None:
            try:
                while True:
                    await _send_once()
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.debug("Ping loop cancelled")
            except WebSocketError:
                logger.debug("Ping loop stopped: the connection is gone")

        self._ping_task = asyncio.create_task(_ping_loop())
        logger.debug("Ping loop started with interval=%.1fs", interval)

    async def subscribe_symbol_ohlcv(
        self,
        symbols: list[str],
        interval: Timeframe | StreamInterval,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to OHLCV channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            interval: Candle interval: ``tick``, ``1m`` or ``5m`` (the only ones the stream
                      serves; others raise ``ValidationError``).
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_ohlcv_request(StreamingMethod.SUBSCRIBE, symbols, interval),
            on_response,
        )

    async def subscribe_symbol_trade(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to trade channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "trade", symbols
            ),
            on_response,
        )

    async def subscribe_symbol_quote(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to quote channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "quote", symbols
            ),
            on_response,
        )

    async def subscribe_symbol_room(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to foreign room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "room", symbols
            ),
            on_response,
        )

    async def subscribe_symbol_put_through(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to put-through channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "put", symbols
            ),
            on_response,
        )

    async def subscribe_symbol_odd_lot(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to odd-lot channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "oddlot", symbols
            ),
            on_response,
        )

    async def subscribe_symbol(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to trade, quote, and foreign-room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self.subscribe_symbol_trade(symbols, on_response)
        await self.subscribe_symbol_quote(symbols, on_response)
        await self.subscribe_symbol_room(symbols, on_response)

    async def subscribe_board(
        self,
        boards: list[Board],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to trade, quote, and foreign-room channels for the given boards.

        Args:
            boards: List of Board enums to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        board_values = [board.value for board in boards]
        await self.subscribe_symbol_trade(board_values, on_response)
        await self.subscribe_symbol_quote(board_values, on_response)
        await self.subscribe_symbol_room(board_values, on_response)

    async def subscribe_index(
        self,
        indices: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to trade, quote, and foreign-room channels for the given indices.

        These are ``trade.<index>`` topics, i.e. the trades of the index's constituent
        symbols. For the ticks of the index itself use ``subscribe_index_trade``.

        Args:
            indices: List of index codes to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self.subscribe_symbol_trade(indices, on_response)
        await self.subscribe_symbol_quote(indices, on_response)
        await self.subscribe_symbol_room(indices, on_response)

    async def unsubscribe_symbol_trade(self, symbols: list[str]) -> None:
        """Unsubscribe from trade channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        await self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "trade", symbols
            ).to_dict()
        )

    async def unsubscribe_symbol_quote(self, symbols: list[str]) -> None:
        """Unsubscribe from quote channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        await self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "quote", symbols
            ).to_dict()
        )

    async def unsubscribe_symbol_room(self, symbols: list[str]) -> None:
        """Unsubscribe from foreign room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        await self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "room", symbols
            ).to_dict()
        )

    async def unsubscribe_symbol_put_through(self, symbols: list[str]) -> None:
        """Unsubscribe from put-through channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        await self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "put", symbols
            ).to_dict()
        )

    async def unsubscribe_symbol_odd_lot(self, symbols: list[str]) -> None:
        """Unsubscribe from odd-lot channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        await self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "oddlot", symbols
            ).to_dict()
        )

    async def subscribe_market_flag(
        self,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to market session flags (ATO, LO, ATC, ...) for all boards.

        Args:
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_market_flag_request(StreamingMethod.SUBSCRIBE),
            on_response,
        )

    async def unsubscribe_market_flag(self) -> None:
        """Unsubscribe from market session flags.
        """
        await self._ws.send(
            _build_market_flag_request(StreamingMethod.UNSUBSCRIBE).to_dict()
        )

    async def list_subscription(self, timeout: float = 5.0) -> dict[str, list[str]]:
        """Ask the server which topics this connection is subscribed to.

        Args:
            timeout: Seconds to wait for the reply.

        Returns:
            ``{"trading": [...], "data": [...]}``; a channel with nothing subscribed is an empty
            list.

        Raises:
            WebSocketError: If not connected, or no reply arrives within ``timeout``.
        """
        loop = asyncio.get_running_loop()
        reply: asyncio.Future = loop.create_future()

        def _on_reply(message: dict) -> None:
            if not reply.done():
                reply.set_result(split_subscriptions(message))

        self._ws.on(WS_ROUTE_LIST_SUBSCRIPTION, _on_reply)
        try:
            await self._ws.send(_build_list_subscription_request())
            return await asyncio.wait_for(reply, timeout)
        except asyncio.TimeoutError as exc:
            raise WebSocketError("Timed out waiting for the LIST_SUBSCRIPTION reply") from exc
        finally:
            self._ws.off(WS_ROUTE_LIST_SUBSCRIPTION, _on_reply)

    async def subscribe_market(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to master data (ceiling, floor, reference price) for symbols or boards.

        Args:
            symbols: Ticker symbols or board names (e.g. ``HOSE``).
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_data_request(StreamingMethod.SUBSCRIBE, "market", symbols), on_response
        )

    async def unsubscribe_market(self, symbols: list[str]) -> None:
        """Unsubscribe from master data for the given symbols or boards.

        Args:
            symbols: Ticker symbols (or board names such as ``"HOSE"``), e.g. ``["SSI",
                     "VNM"]``.
        """
        await self._ws.send(
            _build_data_request(StreamingMethod.UNSUBSCRIBE, "market", symbols).to_dict()
        )

    async def subscribe_index_trade(
        self,
        indices: list[str],
        interval: Timeframe | StreamInterval | None = None,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to the ticks of the index itself (``trade.index.<code>``).

        Ticks arrive as ``IndexTickMessage``; with ``interval`` ``"1m"``/``"5m"`` as candles
        (``IntervalMessage``).

        This differs from ``subscribe_index``, whose ``trade.<index>`` topics carry the
        trades of the index's *constituent* symbols.

        Args:
            indices: Index codes, e.g. ``VN30``. ``UPCOMINDEX`` is sent as ``HNXUPCOMINDEX``.
            interval: Optional ``tick``, ``1m`` or ``5m``; needs a concrete index (no wildcard).
            on_response: Optional callback for the subscribe acknowledgement.
        """
        request = RequestMessage(
            method=StreamingMethod.SUBSCRIBE,
            channel=StreamingChannel.DATA,
            topics=build_topics("trade.index", indices, interval),
        )
        await self._subscribe(request, on_response)

    async def unsubscribe_index_trade(
        self, indices: list[str], interval: Timeframe | StreamInterval | None = None
    ) -> None:
        """Unsubscribe from ``trade.index.<code>`` topics (same ``interval`` as subscribed).

        Args:
            indices: Index codes, e.g. ``["VN30"]``.
            interval: Candle interval: ``"tick"``, ``"1m"`` or ``"5m"`` (the only ones the
                      stream serves); pass the same value you subscribed with.
        """
        request = RequestMessage(
            method=StreamingMethod.UNSUBSCRIBE,
            channel=StreamingChannel.DATA,
            topics=build_topics("trade.index", indices, interval),
        )
        await self._ws.send(request.to_dict())

    async def subscribe_index_summary(
        self,
        indices: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to index summaries (``indexsummary.<code>``).

        Delivered as ``IndexSummaryMessage`` (``on_index_summary`` / ``on_data``); its ``data``
        keeps the server's fields untouched.

        Args:
            indices: Index codes, e.g. ``VN30``.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_data_request(StreamingMethod.SUBSCRIBE, "indexsummary", indices),
            on_response,
        )

    async def unsubscribe_index_summary(self, indices: list[str]) -> None:
        """Unsubscribe from index summaries for the given index codes.

        Args:
            indices: Index codes, e.g. ``["VN30"]``.
        """
        await self._ws.send(
            _build_data_request(StreamingMethod.UNSUBSCRIBE, "indexsummary", indices).to_dict()
        )

    async def unsubscribe_symbol_ohlcv(
        self, symbols: list[str], interval: Timeframe | StreamInterval
    ) -> None:
        """Unsubscribe from OHLCV channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
            interval: Timeframe of the OHLCV candles to unsubscribe.
        """
        await self._ws.send(
            _build_ohlcv_request(
                StreamingMethod.UNSUBSCRIBE, symbols, interval
            ).to_dict()
        )

    async def unsubscribe_symbol(self, symbols: list[str]) -> None:
        """Unsubscribe from trade, quote, and foreign-room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        await self.unsubscribe_symbol_trade(symbols)
        await self.unsubscribe_symbol_quote(symbols)
        await self.unsubscribe_symbol_room(symbols)

    async def unsubscribe_board(self, boards: list[Board]) -> None:
        """Unsubscribe from trade, quote, and foreign-room channels for the given boards.

        Args:
            boards: List of Board enums to unsubscribe from.
        """
        board_values = [board.value for board in boards]
        await self.unsubscribe_symbol_trade(board_values)
        await self.unsubscribe_symbol_quote(board_values)
        await self.unsubscribe_symbol_room(board_values)

    async def unsubscribe_index(self, indices: list[str]) -> None:
        """Unsubscribe from trade, quote, and foreign-room channels for the given indices.

        Args:
            indices: List of index codes to unsubscribe from.
        """
        await self.unsubscribe_symbol_trade(indices)
        await self.unsubscribe_symbol_quote(indices)
        await self.unsubscribe_symbol_room(indices)

    async def subscribe_order_status(
        self,
        account_no: str = "*",
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to order status updates.

        The callback will be invoked with the raw message dict whenever a new
        order status message is received on the TRADING channel.

        Args:
            account_no: Account number to subscribe to; "*" for all accounts.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_trading_request(StreamingMethod.SUBSCRIBE, "order", account_no),
            on_response,
        )

    async def subscribe_portfolio(
        self,
        account_no: str = "*",
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to portfolio changes.

        The callback will be invoked with the raw message dict whenever a new
        portfolio message is received on the TRADING channel.

        Args:
            account_no: Account number to subscribe to; "*" for all accounts.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        await self._subscribe(
            _build_trading_request(StreamingMethod.SUBSCRIBE, "portfolio", account_no),
            on_response,
        )

    async def unsubscribe_order_status(self, account_no: str = "*") -> None:
        """Unsubscribe from ``order.<account>`` events (use the account given to subscribe).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
        """
        await self._ws.send(
            _build_trading_request(StreamingMethod.UNSUBSCRIBE, "order", account_no).to_dict()
        )

    async def unsubscribe_portfolio(self, account_no: str = "*") -> None:
        """Unsubscribe from ``portfolio.<account>`` events.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
        """
        await self._ws.send(
            _build_trading_request(
                StreamingMethod.UNSUBSCRIBE, "portfolio", account_no
            ).to_dict()
        )

    async def unsubscribe_all(self) -> dict[str, list[str]]:
        """Unsubscribe from everything this connection is subscribed to.

        Asks the server what is subscribed (``list_subscription``) and removes exactly that, so
        it also clears topics subscribed by an earlier run of the same session.

        Returns:
            The topics that were removed: ``{"data": [...], "trading": [...]}``.
        """
        current = await self.list_subscription()
        channels = {"data": StreamingChannel.DATA, "trading": StreamingChannel.TRADING}
        for key, channel in channels.items():
            if current.get(key):
                request = RequestMessage(
                    method=StreamingMethod.UNSUBSCRIBE, channel=channel, topics=current[key]
                )
                await self._ws.send(request.to_dict())
        return current

    async def connect(self) -> None:
        """Open the WebSocket connection.
        """
        await self._ws.connect()

    async def disconnect(self) -> None:
        """Close the WebSocket connection (and stop the ping loop, if one is running).
        """
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        await self._ws.disconnect()

    async def wait(self, timeout: float | None = None) -> None:
        """Await until the connection is closed or *timeout* seconds elapse.

        Args:
            timeout: Maximum number of seconds to wait, or None to wait indefinitely.
        """
        await self._ws.wait(timeout)


# ---------------------------------------------------------------------------
# Sync service
# ---------------------------------------------------------------------------

    # -- clearer names -------------------------------------------------
    # Same methods under names that say what arrives; the original names keep working.
    subscribe_orders = subscribe_order_status  # order status AND fills (OrderMatchMessage)
    subscribe_index_ticks = subscribe_index_trade  # ticks of the index itself
    subscribe_master_data = subscribe_market  # ceiling / floor / reference price
    subscribe_session_flag = subscribe_market_flag  # ATO / LO / ATC ... per board
    unsubscribe_orders = unsubscribe_order_status
    unsubscribe_index_ticks = unsubscribe_index_trade
    unsubscribe_master_data = unsubscribe_market
    unsubscribe_session_flag = unsubscribe_market_flag
    # The classic topics too:
    subscribe_trades = subscribe_symbol_trade  # trade.<symbol>: matched trades
    subscribe_quotes = subscribe_symbol_quote  # quote.<symbol>: bid/ask depth
    subscribe_foreign_room = subscribe_symbol_room  # room.<symbol>: foreign room
    subscribe_put_through = subscribe_symbol_put_through  # put.<symbol>: negotiated trades
    subscribe_odd_lot = subscribe_symbol_odd_lot  # oddlot.<symbol>: odd-lot trades
    subscribe_candles = subscribe_symbol_ohlcv  # trade.<symbol>@tick|1m|5m
    subscribe_exchange_trades = subscribe_board  # trade/quote/room of a whole exchange
    subscribe_index_constituents = subscribe_index  # trade/quote/room of an index's members
    subscribe_positions = subscribe_portfolio  # portfolio.<account>: derivative positions
    unsubscribe_trades = unsubscribe_symbol_trade
    unsubscribe_quotes = unsubscribe_symbol_quote
    unsubscribe_foreign_room = unsubscribe_symbol_room
    unsubscribe_put_through = unsubscribe_symbol_put_through
    unsubscribe_odd_lot = unsubscribe_symbol_odd_lot
    unsubscribe_candles = unsubscribe_symbol_ohlcv
    unsubscribe_exchange_trades = unsubscribe_board
    unsubscribe_index_constituents = unsubscribe_index
    unsubscribe_positions = unsubscribe_portfolio


class StreamingService(_CallbackProperties):
    """Synchronous unified real-time streaming via a single WebSocket connection.

    Market data channels: trade, quote, market-status, foreign-room, put, oddlot.
    Portfolio channels: order-status, portfolio.
    """

    def __init__(self, ws_client: WebSocketClient):
        """Initialise the service with a synchronous WebSocket client."""
        self._ws = ws_client
        self._on_data_callbacks: Callable[[DataMessage], Any] | None = None
        self._on_trading_callbacks: Callable[[TradingMessage], Any] | None = None
        self._on_heartbeat_callbacks: Callable[[HeartbeatMessage], Any] | None = None
        self._typed: dict[str, Callable | None] = {}
        self._ping_thread: threading.Thread | None = None
        self._ping_stop = threading.Event()

    @property
    def on_data(self) -> Callable[[DataMessage], Any] | None:
        """Get the current callback for market data messages.

        Returns:
            The current market data callback, or None if not set.
        """
        return self._on_data_callbacks

    @on_data.setter
    def on_data(self, callback: Callable[[DataMessage], Any] | None) -> None:
        """Set a callback for market data messages.

        The callback will be invoked with the raw message dict whenever a new
        market data message is received on the DATA channel.

        Args:
            callback: Callback invoked with each market data message, or None to clear.
        """
        self._on_data_callbacks = callback
        self._refresh_handlers()

    @property
    def on_trading(self) -> Callable[[TradingMessage], Any] | None:
        """Get the current callback for trading messages.

        Returns:
            The current trading callback, or None if not set.
        """
        return self._on_trading_callbacks

    @on_trading.setter
    def on_trading(
        self, callback: Callable[[TradingMessage], Any] | None
    ) -> None:
        """Set a callback for trading messages.

        The callback will be invoked with an OrderStatusMessage or PortfolioMessage
        depending on the topic, whenever a new message is received on the TRADING channel.

        Args:
            callback: Callback invoked with each trading message, or None to clear.
        """
        self._on_trading_callbacks = callback
        self._refresh_handlers()

    @property
    def on_heartbeat(self) -> Callable[[HeartbeatMessage], Any] | None:
        """Get the current callback for heartbeat messages.

        Returns:
            The current heartbeat callback, or None if not set.
        """
        return self._on_heartbeat_callbacks

    @on_heartbeat.setter
    def on_heartbeat(self, callback: Callable[[HeartbeatMessage], Any] | None) -> None:
        """Set a callback for heartbeat messages.

        The callback will be invoked with a HeartbeatMessage whenever a new
        heartbeat message is received on the HEARTBEAT channel.

        Args:
            callback: Callback invoked with each heartbeat message, or None to clear.
        """
        self._on_heartbeat_callbacks = callback
        self._ws.on(
            StreamingChannel.HEARTBEAT.value,
            (lambda msg: callback(HeartbeatMessage.from_dict(msg)))
            if callback is not None
            else None,
        )

    # ------------------------------------------------------------------
    # Market data subscriptions
    # ------------------------------------------------------------------

    def _deliver(self, callbacks: list[Callable], message: Any) -> None:
        """Call each callback with ``message``; a failing one must not starve the others."""
        for callback in callbacks:
            try:
                callback(message)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error in a streaming callback")

    def _handle_data(self, msg: dict) -> None:
        message = _parse_data_message(msg)
        targets = [cb for cb in [self._on_data_callbacks] if cb is not None]
        targets += _typed_targets(self._typed, "data", message)
        self._deliver(targets, message)

    def _handle_trading(self, msg: dict) -> None:
        message = _parse_trading_message(msg)
        targets = [cb for cb in [self._on_trading_callbacks] if cb is not None]
        targets += _typed_targets(self._typed, "trading", message)
        self._deliver(targets, message)

    def _refresh_handlers(self) -> None:
        """Install (or clear) the one handler per channel from the callbacks currently set."""
        wants_data = self._on_data_callbacks is not None or any(
            self._typed.get(k) for k, (chan, _) in _TYPED_CALLBACKS.items() if chan == "data"
        )
        wants_trading = self._on_trading_callbacks is not None or any(
            self._typed.get(k) for k, (chan, _) in _TYPED_CALLBACKS.items() if chan == "trading"
        )
        self._ws.on(StreamingChannel.DATA.value, self._handle_data if wants_data else None)
        self._ws.on(
            StreamingChannel.TRADING.value, self._handle_trading if wants_trading else None
        )


    def _subscribe(
        self, request: RequestMessage, on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Helper to subscribe to a channel with an optional callback."""
        if on_response is not None:
            # Acknowledgements have their own route: registering on the request's channel
            # would replace the user's data/trading handler.
            self._ws.on(WS_ROUTE_ACK, on_response)
        self._ws.send(request.to_dict())

    # Heartbeat channel is special - we want to allow pinging without needing to set a callback
    def ping(
        self,
        on_response: Callable[[dict], Any] | None = None,
        interval: float | None = None,
    ) -> None:
        """Send a ping to the WebSocket server.

        Args:
            on_response: Optional callback for the ping response.
            interval: If provided, send a ping every *interval* seconds in the background.
                      Calling ping() again cancels the previous loop. Pass ``interval=None`` to
                      send a single ping.
        """

        def _send_once() -> None:
            logger.debug("Sending ping to WebSocket server")
            self._subscribe(
                RequestMessage(
                    method=StreamingMethod.PING_PONG,
                    channel=StreamingChannel.HEARTBEAT,
                ),
                on_response,
            )
            logger.debug("Ping sent to WebSocket server")

        if interval is None:
            _send_once()
            return

        # Stop any existing ping loop
        self._ping_stop.set()
        if self._ping_thread and self._ping_thread.is_alive():
            self._ping_thread.join(timeout=interval + 1)

        self._ping_stop.clear()

        def _ping_loop() -> None:
            while not self._ping_stop.wait(timeout=interval):
                try:
                    _send_once()
                except WebSocketError:
                    logger.debug("Ping loop stopped: the connection is gone")
                    return

        self._ping_thread = threading.Thread(target=_ping_loop, daemon=True, name="ssi-ping-loop")
        self._ping_thread.start()
        logger.debug("Ping loop started with interval=%.1fs", interval)

    # Data channels: trade, quote, market-status, foreign-room, put, oddlot
    def subscribe_symbol_ohlcv(
        self,
        symbols: list[str],
        interval: Timeframe | StreamInterval,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to OHLCV channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            interval: Candle interval: ``tick``, ``1m`` or ``5m`` (the only ones the stream
                      serves; others raise ``ValidationError``).
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_ohlcv_request(StreamingMethod.SUBSCRIBE, symbols, interval),
            on_response,
        )

    def subscribe_symbol_trade(
        self, symbols: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to trade channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "trade", symbols
            ),
            on_response,
        )

    def subscribe_symbol_quote(
        self, symbols: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to quote channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "quote", symbols
            ),
            on_response,
        )

    def subscribe_symbol_room(
        self, symbols: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to foreign room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "room", symbols
            ),
            on_response,
        )

    def subscribe_symbol_put_through(
        self, symbols: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to put-through channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "put", symbols
            ),
            on_response,
        )

    def subscribe_symbol_odd_lot(
        self, symbols: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to odd-lot channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_subscribe_request(
                StreamingMethod.SUBSCRIBE, StreamingChannel.DATA, "oddlot", symbols
            ),
            on_response,
        )

    def subscribe_symbol(
        self, symbols: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to trade, quote, and foreign-room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self.subscribe_symbol_trade(symbols, on_response)
        self.subscribe_symbol_quote(symbols, on_response)
        self.subscribe_symbol_room(symbols, on_response)

    def subscribe_board(
        self, boards: list[Board], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to trade, quote, and foreign-room channels for the given boards.

        Args:
            boards: List of Board enums to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        boards = [board.value for board in boards]
        self.subscribe_symbol_trade(boards, on_response)
        self.subscribe_symbol_quote(boards, on_response)
        self.subscribe_symbol_room(boards, on_response)

    def subscribe_index(
        self, indices: list[str], on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to trade, quote, and foreign-room channels for the given indices.

        These are ``trade.<index>`` topics, i.e. the trades of the index's constituent
        symbols. For the ticks of the index itself use ``subscribe_index_trade``.

        Args:
            indices: List of index codes to subscribe to.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self.subscribe_symbol_trade(indices, on_response)
        self.subscribe_symbol_quote(indices, on_response)
        self.subscribe_symbol_room(indices, on_response)

    def unsubscribe_symbol_trade(self, symbols: list[str]) -> None:
        """Unsubscribe from trade channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "trade", symbols
            ).to_dict()
        )

    def unsubscribe_symbol_quote(self, symbols: list[str]) -> None:
        """Unsubscribe from quote channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "quote", symbols
            ).to_dict()
        )

    def unsubscribe_symbol_room(self, symbols: list[str]) -> None:
        """Unsubscribe from foreign room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "room", symbols
            ).to_dict()
        )

    def unsubscribe_symbol_put_through(self, symbols: list[str]) -> None:
        """Unsubscribe from put-through channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "put", symbols
            ).to_dict()
        )

    def unsubscribe_symbol_odd_lot(self, symbols: list[str]) -> None:
        """Unsubscribe from odd-lot channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        self._ws.send(
            _build_subscribe_request(
                StreamingMethod.UNSUBSCRIBE, StreamingChannel.DATA, "oddlot", symbols
            ).to_dict()
        )

    def subscribe_market_flag(self, on_response: Callable[[dict], Any] | None = None) -> None:
        """Subscribe to market session flags (ATO, LO, ATC, ...) for all boards.

        Args:
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_market_flag_request(StreamingMethod.SUBSCRIBE),
            on_response,
        )

    def unsubscribe_market_flag(self) -> None:
        """Unsubscribe from market session flags.
        """
        self._ws.send(
            _build_market_flag_request(StreamingMethod.UNSUBSCRIBE).to_dict()
        )

    def list_subscription(self, timeout: float = 5.0) -> dict[str, list[str]]:
        """Ask the server which topics this connection is subscribed to.

        Args:
            timeout: Seconds to wait for the reply.

        Returns:
            ``{"trading": [...], "data": [...]}``; a channel with nothing subscribed is an empty
            list.

        Raises:
            WebSocketError: If not connected, or no reply arrives within ``timeout``.
        """
        arrived = threading.Event()
        result: dict[str, list[str]] = {}

        def _on_reply(message: dict) -> None:
            result.update(split_subscriptions(message))
            arrived.set()

        self._ws.on(WS_ROUTE_LIST_SUBSCRIPTION, _on_reply)
        try:
            self._ws.send(_build_list_subscription_request())
            if not arrived.wait(timeout):
                raise WebSocketError("Timed out waiting for the LIST_SUBSCRIPTION reply")
            return result
        finally:
            self._ws.off(WS_ROUTE_LIST_SUBSCRIPTION, _on_reply)

    def subscribe_market(
        self,
        symbols: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to master data (ceiling, floor, reference price) for symbols or boards.

        Args:
            symbols: Ticker symbols or board names (e.g. ``HOSE``).
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_data_request(StreamingMethod.SUBSCRIBE, "market", symbols), on_response
        )

    def unsubscribe_market(self, symbols: list[str]) -> None:
        """Unsubscribe from master data for the given symbols or boards.

        Args:
            symbols: Ticker symbols (or board names such as ``"HOSE"``), e.g. ``["SSI",
                     "VNM"]``.
        """
        self._ws.send(
            _build_data_request(StreamingMethod.UNSUBSCRIBE, "market", symbols).to_dict()
        )

    def subscribe_index_trade(
        self,
        indices: list[str],
        interval: Timeframe | StreamInterval | None = None,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to the ticks of the index itself (``trade.index.<code>``).

        Ticks arrive as ``IndexTickMessage``; with ``interval`` ``"1m"``/``"5m"`` as candles
        (``IntervalMessage``).

        This differs from ``subscribe_index``, whose ``trade.<index>`` topics carry the
        trades of the index's *constituent* symbols.

        Args:
            indices: Index codes, e.g. ``VN30``. ``UPCOMINDEX`` is sent as ``HNXUPCOMINDEX``.
            interval: Optional ``tick``, ``1m`` or ``5m``; needs a concrete index (no wildcard).
            on_response: Optional callback for the subscribe acknowledgement.
        """
        request = RequestMessage(
            method=StreamingMethod.SUBSCRIBE,
            channel=StreamingChannel.DATA,
            topics=build_topics("trade.index", indices, interval),
        )
        self._subscribe(request, on_response)

    def unsubscribe_index_trade(
        self, indices: list[str], interval: Timeframe | StreamInterval | None = None
    ) -> None:
        """Unsubscribe from ``trade.index.<code>`` topics (same ``interval`` as subscribed).

        Args:
            indices: Index codes, e.g. ``["VN30"]``.
            interval: Candle interval: ``"tick"``, ``"1m"`` or ``"5m"`` (the only ones the
                      stream serves); pass the same value you subscribed with.
        """
        request = RequestMessage(
            method=StreamingMethod.UNSUBSCRIBE,
            channel=StreamingChannel.DATA,
            topics=build_topics("trade.index", indices, interval),
        )
        self._ws.send(request.to_dict())

    def subscribe_index_summary(
        self,
        indices: list[str],
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to index summaries (``indexsummary.<code>``).

        Delivered as ``IndexSummaryMessage`` (``on_index_summary`` / ``on_data``); its ``data``
        keeps the server's fields untouched.

        Args:
            indices: Index codes, e.g. ``VN30``.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_data_request(StreamingMethod.SUBSCRIBE, "indexsummary", indices),
            on_response,
        )

    def unsubscribe_index_summary(self, indices: list[str]) -> None:
        """Unsubscribe from index summaries for the given index codes.

        Args:
            indices: Index codes, e.g. ``["VN30"]``.
        """
        self._ws.send(
            _build_data_request(StreamingMethod.UNSUBSCRIBE, "indexsummary", indices).to_dict()
        )

    def unsubscribe_symbol_ohlcv(
        self, symbols: list[str], interval: Timeframe | StreamInterval
    ) -> None:
        """Unsubscribe from OHLCV channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
            interval: Timeframe of the OHLCV candles to unsubscribe.
        """
        self._ws.send(
            _build_ohlcv_request(
                StreamingMethod.UNSUBSCRIBE, symbols, interval
            ).to_dict()
        )

    def unsubscribe_symbol(self, symbols: list[str]) -> None:
        """Unsubscribe from trade, quote, and foreign-room channels for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        self.unsubscribe_symbol_trade(symbols)
        self.unsubscribe_symbol_quote(symbols)
        self.unsubscribe_symbol_room(symbols)

    def unsubscribe_board(self, boards: list[Board]) -> None:
        """Unsubscribe from trade, quote, and foreign-room channels for the given boards.

        Args:
            boards: List of Board enums to unsubscribe from.
        """
        boards = [board.value for board in boards]
        self.unsubscribe_symbol_trade(boards)
        self.unsubscribe_symbol_quote(boards)
        self.unsubscribe_symbol_room(boards)

    def unsubscribe_index(self, indices: list[str]) -> None:
        """Unsubscribe from trade, quote, and foreign-room channels for the given indices.

        Args:
            indices: List of index codes to unsubscribe from.
        """
        self.unsubscribe_symbol_trade(indices)
        self.unsubscribe_symbol_quote(indices)
        self.unsubscribe_symbol_room(indices)

    # Trading channels: order-status, portfolio
    def subscribe_order_status(
        self, account_no: str = "*", on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to order status updates.

        The callback will be invoked with the raw message dict whenever a new
        order status message is received on the TRADING channel.

        Args:
            account_no: Account number to subscribe to; "*" for all accounts.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_trading_request(StreamingMethod.SUBSCRIBE, "order", account_no),
            on_response,
        )

    def subscribe_portfolio(
        self, account_no: str = "*", on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Subscribe to portfolio changes.

        The callback will be invoked with the raw message dict whenever a new
        portfolio message is received on the TRADING channel.

        Args:
            account_no: Account number to subscribe to; "*" for all accounts.
            on_response: Optional callback for the subscribe acknowledgement.
        """
        self._subscribe(
            _build_trading_request(StreamingMethod.SUBSCRIBE, "portfolio", account_no),
            on_response,
        )

    # Waiting for messages
    def unsubscribe_order_status(self, account_no: str = "*") -> None:
        """Unsubscribe from ``order.<account>`` events (use the account given to subscribe).

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
        """
        self._ws.send(
            _build_trading_request(StreamingMethod.UNSUBSCRIBE, "order", account_no).to_dict()
        )

    def unsubscribe_portfolio(self, account_no: str = "*") -> None:
        """Unsubscribe from ``portfolio.<account>`` events.

        Args:
            account_no: Trading account number, e.g. ``"1234561"`` (derivative accounts end in
                        ``8``).
        """
        self._ws.send(
            _build_trading_request(
                StreamingMethod.UNSUBSCRIBE, "portfolio", account_no
            ).to_dict()
        )

    def unsubscribe_all(self) -> dict[str, list[str]]:
        """Unsubscribe from everything this connection is subscribed to.

        Asks the server what is subscribed (``list_subscription``) and removes exactly that, so
        it also clears topics subscribed by an earlier run of the same session.

        Returns:
            The topics that were removed: ``{"data": [...], "trading": [...]}``.
        """
        current = self.list_subscription()
        channels = {"data": StreamingChannel.DATA, "trading": StreamingChannel.TRADING}
        for key, channel in channels.items():
            if current.get(key):
                request = RequestMessage(
                    method=StreamingMethod.UNSUBSCRIBE, channel=channel, topics=current[key]
                )
                self._ws.send(request.to_dict())
        return current

    def connect(self) -> None:
        """Open the WebSocket connection.
        """
        self._ws.connect()

    def disconnect(self) -> None:
        """Close the WebSocket connection (and stop the ping loop, if one is running).
        """
        self._ping_stop.set()
        self._ws.disconnect()

    def wait(self, timeout: float | None = None) -> None:
        """Await until the connection is closed or *timeout* seconds elapse.

        Args:
            timeout: Maximum number of seconds to wait, or None to wait indefinitely.
        """
        self._ws.wait(timeout)

    # -- clearer names -------------------------------------------------
    # Same methods under names that say what arrives; the original names keep working.
    subscribe_orders = subscribe_order_status  # order status AND fills (OrderMatchMessage)
    subscribe_index_ticks = subscribe_index_trade  # ticks of the index itself
    subscribe_master_data = subscribe_market  # ceiling / floor / reference price
    subscribe_session_flag = subscribe_market_flag  # ATO / LO / ATC ... per board
    unsubscribe_orders = unsubscribe_order_status
    unsubscribe_index_ticks = unsubscribe_index_trade
    unsubscribe_master_data = unsubscribe_market
    unsubscribe_session_flag = unsubscribe_market_flag
    # The classic topics too:
    subscribe_trades = subscribe_symbol_trade  # trade.<symbol>: matched trades
    subscribe_quotes = subscribe_symbol_quote  # quote.<symbol>: bid/ask depth
    subscribe_foreign_room = subscribe_symbol_room  # room.<symbol>: foreign room
    subscribe_put_through = subscribe_symbol_put_through  # put.<symbol>: negotiated trades
    subscribe_odd_lot = subscribe_symbol_odd_lot  # oddlot.<symbol>: odd-lot trades
    subscribe_candles = subscribe_symbol_ohlcv  # trade.<symbol>@tick|1m|5m
    subscribe_exchange_trades = subscribe_board  # trade/quote/room of a whole exchange
    subscribe_index_constituents = subscribe_index  # trade/quote/room of an index's members
    subscribe_positions = subscribe_portfolio  # portfolio.<account>: derivative positions
    unsubscribe_trades = unsubscribe_symbol_trade
    unsubscribe_quotes = unsubscribe_symbol_quote
    unsubscribe_foreign_room = unsubscribe_symbol_room
    unsubscribe_put_through = unsubscribe_symbol_put_through
    unsubscribe_odd_lot = unsubscribe_symbol_odd_lot
    unsubscribe_candles = unsubscribe_symbol_ohlcv
    unsubscribe_exchange_trades = unsubscribe_board
    unsubscribe_index_constituents = unsubscribe_index
    unsubscribe_positions = unsubscribe_portfolio
