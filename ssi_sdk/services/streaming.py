"""
Module: ssi_sdk.services.streaming
Provides the StreamingService class for real-time market data and trading updates via WebSocket.
The StreamingService allows subscribing to various channels
(trade, quote, order status, portfolio, etc.)
and handles incoming messages with user-defined callbacks.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

from ssi_sdk.enums import Board, DataTopic, StreamingChannel, StreamingMethod, Timeframe
from ssi_sdk.models import (
    ForeignRoomMessage,
    HeartbeatMessage,
    MarketStatusMessage,
    OddLotMessage,
    OrderStatusMessage,
    PortfolioMessage,
    PutMessage,
    QuoteMessage,
    RequestMessage,
    TradeMessage,
    FCOOrderUpdateMessage,
)
from ssi_sdk.models.streaming import IntervalMessage
from ssi_sdk.transport.websocket_client import AsyncWebSocketClient, WebSocketClient

logger = logging.getLogger("ssi_sdk.services.streaming")


# ---------------------------------------------------------------------------
# Shared helpers (used by both AsyncStreamingService and StreamingService)
# ---------------------------------------------------------------------------


def _wrap_data_callback(callback: Callable) -> Callable:
    """Wrap a user callback to deserialise DATA-channel messages by topic."""

    def _wrap(msg: dict) -> Any:
        topic: str = msg.get("topic", "")
        logger.debug(f"DATA RAW: {msg}")
        if topic.startswith(DataTopic.TRADE.value):
            if any(topic.endswith(f"@{tf.value}") for tf in Timeframe):
                return callback(IntervalMessage.from_dict(msg.get("data", {})))
            return callback(TradeMessage.from_dict(msg.get("data", {})))
        if topic.startswith(DataTopic.QUOTE.value):
            return callback(QuoteMessage.from_dict(msg.get("data", {})))
        if topic.startswith(DataTopic.ROOM.value):
            return callback(ForeignRoomMessage.from_dict(msg.get("data", {})))
        if topic.startswith(DataTopic.MARKET.value):
            return callback(MarketStatusMessage.from_dict(msg.get("data", {})))
        if topic.startswith(DataTopic.PUT.value):
            return callback(PutMessage.from_dict(msg.get("data", {})))
        if topic.startswith(DataTopic.ODD_LOT.value):
            return callback(OddLotMessage.from_dict(msg.get("data", {})))
        return callback(msg)

    return _wrap


def _wrap_trading_callback(callback: Callable) -> Callable:
    """Wrap a user callback to deserialise TRADING-channel messages by topic."""

    def _wrap(msg: dict) -> Any:
        topic: str = msg.get("topic", "")
        logger.debug(f"TRADING RAW: {msg}")
        if topic.startswith("order."):
            if msg.get("data", {}).get("eventType") == "fcoEvent":
                return callback(FCOOrderUpdateMessage.from_dict(msg.get("data", {})))
            else:
                return callback(OrderStatusMessage.from_dict(msg.get("data", {})))
        if topic.startswith("portfolio."):
            return callback(PortfolioMessage.from_dict(msg.get("data", {})))
        return callback(msg)

    return _wrap


def _build_subscribe_request(
    method: StreamingMethod,
    channel: StreamingChannel,
    topic_prefix: str,
    symbols: list[str],
) -> RequestMessage:
    """Build a subscribe/unsubscribe RequestMessage for the given symbols."""
    topics = [f"{topic_prefix}.{s}" for s in symbols]
    return RequestMessage(method=method, channel=channel, topics=topics)


def _build_ohlcv_request(
    method: StreamingMethod,
    symbols: list[str],
    interval: Timeframe,
) -> RequestMessage:
    """Build a subscribe/unsubscribe RequestMessage for OHLCV channels."""
    topics = [f"trade.{s}@{interval.value}" for s in symbols]
    return RequestMessage(method=method, channel=StreamingChannel.DATA, topics=topics)


# ---------------------------------------------------------------------------
# Async service
# ---------------------------------------------------------------------------


class AsyncStreamingService:
    """Unified real-time streaming via a single WebSocket connection.

    Market data channels: trade, quote, market-status, foreign-room, put, oddlot.
    Portfolio channels: order-status, portfolio.
    """

    def __init__(self, ws_client: AsyncWebSocketClient):
        """Initialise the service with an async WebSocket client."""
        self._ws = ws_client
        self._on_data_callbacks: Callable[[dict], Any] | None = None
        self._on_trading_callbacks: (
            Callable[[OrderStatusMessage | PortfolioMessage], Any] | None
        ) = None
        self._on_heartbeat_callbacks: Callable[[HeartbeatMessage], Any] | None = None
        self._ping_task: asyncio.Task | None = None

    @property
    def on_data(self) -> Callable[[dict], Any] | None:
        """Get the current callback for market data messages.

        Returns:
            The current market data callback, or None if not set.
        """
        return self._on_data_callbacks

    @on_data.setter
    def on_data(self, callback: Callable[[dict], Any] | None) -> None:
        """Set a callback for market data messages.

        The callback will be invoked with the raw message dict whenever a new
        market data message is received on the DATA channel.

        Args:
            callback: Callback invoked with each market data message, or None to clear.
        """
        self._on_data_callbacks = callback
        self._ws.on(
            StreamingChannel.DATA.value,
            _wrap_data_callback(callback) if callback is not None else None,
        )

    @property
    def on_trading(self) -> Callable[[OrderStatusMessage | PortfolioMessage], Any] | None:
        """Get the current callback for trading messages.

        Returns:
            The current trading callback, or None if not set.
        """
        return self._on_trading_callbacks

    @on_trading.setter
    def on_trading(
        self, callback: Callable[[OrderStatusMessage | PortfolioMessage], Any] | None
    ) -> None:
        """Set a callback for trading messages.

        The callback will be invoked with an OrderStatusMessage or PortfolioMessage
        depending on the topic, whenever a new message is received on the TRADING channel.

        Args:
            callback: Callback invoked with each trading message, or None to clear.
        """
        self._on_trading_callbacks = callback
        self._ws.on(
            StreamingChannel.TRADING.value,
            _wrap_trading_callback(callback) if callback is not None else None,
        )

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

    async def _subscribe(
        self,
        request: RequestMessage,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Helper to subscribe to a channel with an optional callback."""
        if on_response is not None:
            self._ws.on(request.channel.value, on_response)
        await self._ws.send(request.to_dict())

    async def ping(
        self,
        on_response: Callable[[dict], Any] | None = None,
        interval: float | None = None,
    ) -> None:
        """Send a ping to the WebSocket server.

        Args:
            on_response: Optional callback for the ping response.
            interval: If provided, send a ping every *interval* seconds in the
                background.  Calling ping() again cancels the previous loop.
                Pass ``interval=None`` to send a single ping.
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

        self._ping_task = asyncio.create_task(_ping_loop())
        logger.debug("Ping loop started with interval=%.1fs", interval)

    async def subscribe_symbol_ohlcv(
        self,
        symbols: list[str],
        interval: Timeframe,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to OHLCV channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            interval: Timeframe of the OHLCV candles.
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

    async def unsubscribe_symbol_ohlcv(
        self, symbols: list[str], interval: Timeframe
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
            RequestMessage(
                method=StreamingMethod.SUBSCRIBE,
                channel=StreamingChannel.TRADING,
                topics=[f"order.{account_no}"],
            ),
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
            RequestMessage(
                method=StreamingMethod.SUBSCRIBE,
                channel=StreamingChannel.TRADING,
                topics=[f"portfolio.{account_no}"],
            ),
            on_response,
        )

    async def connect(self) -> None:
        """Open the WebSocket connection."""
        await self._ws.connect()

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
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


class StreamingService:
    """Synchronous unified real-time streaming via a single WebSocket connection.

    Market data channels: trade, quote, market-status, foreign-room, put, oddlot.
    Portfolio channels: order-status, portfolio.
    """

    def __init__(self, ws_client: WebSocketClient):
        """Initialise the service with a synchronous WebSocket client."""
        self._ws = ws_client
        self._on_data_callbacks: Callable[[dict], Any] | None = None
        self._on_trading_callbacks: (
            Callable[[OrderStatusMessage | PortfolioMessage], Any] | None
        ) = None
        self._on_heartbeat_callbacks: Callable[[HeartbeatMessage], Any] | None = None
        self._ping_thread: threading.Thread | None = None
        self._ping_stop = threading.Event()

    @property
    def on_data(self) -> Callable[[dict], Any] | None:
        """Get the current callback for market data messages.

        Returns:
            The current market data callback, or None if not set.
        """
        return self._on_data_callbacks

    @on_data.setter
    def on_data(self, callback: Callable[[dict], Any] | None) -> None:
        """Set a callback for market data messages.

        The callback will be invoked with the raw message dict whenever a new
        market data message is received on the DATA channel.

        Args:
            callback: Callback invoked with each market data message, or None to clear.
        """
        self._on_data_callbacks = callback
        self._ws.on(
            StreamingChannel.DATA.value,
            _wrap_data_callback(callback) if callback is not None else None,
        )

    @property
    def on_trading(self) -> Callable[[OrderStatusMessage | PortfolioMessage], Any] | None:
        """Get the current callback for trading messages.

        Returns:
            The current trading callback, or None if not set.
        """
        return self._on_trading_callbacks

    @on_trading.setter
    def on_trading(
        self, callback: Callable[[OrderStatusMessage | PortfolioMessage], Any] | None
    ) -> None:
        """Set a callback for trading messages.

        The callback will be invoked with an OrderStatusMessage or PortfolioMessage
        depending on the topic, whenever a new message is received on the TRADING channel.

        Args:
            callback: Callback invoked with each trading message, or None to clear.
        """
        self._on_trading_callbacks = callback
        self._ws.on(
            StreamingChannel.TRADING.value,
            _wrap_trading_callback(callback) if callback is not None else None,
        )

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

    def _subscribe(
        self, request: RequestMessage, on_response: Callable[[dict], Any] | None = None
    ) -> None:
        """Helper to subscribe to a channel with an optional callback."""
        print(request)
        if on_response is not None:
            self._ws.on(request.channel.value, on_response)
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
            interval: If provided, send a ping every *interval* seconds in the
                background.  Calling ping() again cancels the previous loop.
                Pass ``interval=None`` to send a single ping.
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
                _send_once()

        self._ping_thread = threading.Thread(target=_ping_loop, daemon=True, name="ssi-ping-loop")
        self._ping_thread.start()
        logger.debug("Ping loop started with interval=%.1fs", interval)

    # Data channels: trade, quote, market-status, foreign-room, put, oddlot
    def subscribe_symbol_ohlcv(
        self,
        symbols: list[str],
        interval: Timeframe,
        on_response: Callable[[dict], Any] | None = None,
    ) -> None:
        """Subscribe to OHLCV channels for the given symbols.

        Args:
            symbols: List of ticker symbols to subscribe to.
            interval: Timeframe of the OHLCV candles.
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

    def unsubscribe_symbol_ohlcv(
        self, symbols: list[str], interval: Timeframe
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
            RequestMessage(
                method=StreamingMethod.SUBSCRIBE,
                channel=StreamingChannel.TRADING,
                topics=[f"order.{account_no}"],
            ),
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
            RequestMessage(
                method=StreamingMethod.SUBSCRIBE,
                channel=StreamingChannel.TRADING,
                topics=[f"portfolio.{account_no}"],
            ),
            on_response,
        )

    # Waiting for messages
    def connect(self) -> None:
        """Open the WebSocket connection."""
        self._ws.connect()

    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._ws.disconnect()

    def wait(self, timeout: float | None = None) -> None:
        """Await until the connection is closed or *timeout* seconds elapse.

        Args:
            timeout: Maximum number of seconds to wait, or None to wait indefinitely.
        """
        self._ws.wait(timeout)
