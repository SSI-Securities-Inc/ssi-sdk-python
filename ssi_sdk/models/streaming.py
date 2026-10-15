"""Streaming message models (real-time data via WebSocket)."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ssi_sdk.enums import (
    DataType,
    FCOStatus,
    FCOType,
    OrderSide,
    OrderStatus,
    OrderType,
    StreamingChannel,
    StreamingMethod,
    StreamingType,
)
from ssi_sdk.models.fco import parse_fco_common
from ssi_sdk.utils import (
    pick,
    to_decimal,
    to_enum,
    to_int,
    to_number,
    to_opt_float,
)


def _levels(items: object) -> tuple[list[float], list[int]]:
    """Split ``[[price, volume], ...]`` into parallel lists, skipping malformed entries.

    The order the server sent is kept (it is already best-first); nothing is re-sorted.
    """
    prices: list[float] = []
    volumes: list[int] = []
    if not isinstance(items, (list, tuple)):
        return prices, volumes
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            prices.append(to_number(item[0]))
            volumes.append(to_int(item[1]))
    return prices, volumes


def _deprecated_alias(old: str, new: str) -> property:
    """Read-only property exposing a renamed field under its old name."""

    def getter(self):
        warnings.warn(f"{old} is deprecated; use {new}", DeprecationWarning, stacklevel=2)
        return getattr(self, new)

    return property(getter)


def _opt_number(value: object) -> int | float | None:
    """Number or None (not 0) when the server omitted the field."""
    number = to_opt_float(value)
    if number is None:
        return None
    return int(number) if number == int(number) else number


@dataclass
class RequestMessage:
    """Message format for subscribing/unsubscribing to streaming channels.

    Attributes:
        method: Request method.
        channel: Stream channel.
        topics: Topics the request refers to.
    """

    method: StreamingMethod | str = ""
    channel: StreamingChannel | str = ""
    topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert the RequestMessage to a camelCase dict for sending via WebSocket.

        Returns:
            Dict with ``method``, ``channel`` (enum values as strings), and ``topics``.
        """
        method = self.method.value if isinstance(self.method, StreamingMethod) else self.method
        channel = self.channel.value if isinstance(self.channel, StreamingChannel) else self.channel
        return {
            "method": method,
            "channel": channel,
            "topics": self.topics,
        }


@dataclass
class HeartbeatMessage:
    """Heartbeat message from the server.

    Attributes:
        method: Request method.
        channel: Stream channel.
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        message: Server message (for a rejection, the reason).
    """

    method: StreamingMethod | str = ""
    channel: StreamingChannel | str = ""
    status: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> HeartbeatMessage:
        """Build a HeartbeatMessage from a server message dict.

        Never raises: a missing key, an unknown method/channel (kept as the raw string) or
        a non-dict input all yield a usable message. The ping ack is
        ``{"method": "PING_PONG", "channel": "HEARTBEAT", "status": "ok", "message": "pong"}``.

        Args:
            data: Heartbeat payload with ``method``, ``channel``, ``status``, ``message`` keys.
        Returns:
            A populated HeartbeatMessage instance.
        """
        if not isinstance(data, dict):
            data = {}
        return cls(
            method=to_enum(StreamingMethod, data.get("method")) or "",
            channel=to_enum(StreamingChannel, data.get("channel")) or "",
            status=str(data.get("status") or ""),
            message=str(data.get("message") or ""),
        )


@dataclass
class TradeMessage:
    """Real-time trade tick.

    Attributes:
        type: Message/FCO type.
        trading_time: Time of the event as the server sends it.
        symbol: Ticker symbol.
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        quantity: Order quantity (shares/contracts).
        side: Order side: an ``OrderSide``, or the raw string for an unknown value.
        total_volume: Cumulative volume of the day.
        open: Opening price (``None`` if the server did not send it).
        high: Highest price.
        low: Lowest price.
        avg: Average price.
    """

    type: DataType = DataType.TRADE
    trading_time: str = ""
    symbol: str = ""
    price: int | float = 0
    quantity: int = 0
    side: str = ""
    total_volume: int = 0
    open: int | float | None = None
    high: int | float | None = None
    low: int | float | None = None
    avg: int | float | None = None

    @classmethod
    def from_dict(cls, data: dict) -> TradeMessage:
        """Build a TradeMessage from a streamed trade-tick dict.

        Args:
            data: Raw tick with keys ``t`` (time), ``s`` (symbol), ``p`` (price), ``q``
                (quantity), ``si`` (side), ``v`` (total volume), and optionally ``o``/``h``/
                ``l``/``a`` (open/high/low/average). Quantities may arrive as ``"1234.0"``.
        Returns:
            A populated TradeMessage instance, defaulting ``side`` to ``"U"`` when absent.
            The OHLC extras are ``None`` when the server does not send them.
        """
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            price=to_number(data.get("p", 0.0)),
            quantity=to_int(data.get("q", 0)),
            side=data.get("si", "") if data.get("si", "") else "U",
            total_volume=to_int(data.get("v", 0)),
            open=_opt_number(data.get("o")),
            high=_opt_number(data.get("h")),
            low=_opt_number(data.get("l")),
            avg=_opt_number(data.get("a")),
        )


@dataclass
class IndexTickMessage:
    """Tick of an index itself, from ``trade.index.<code>`` (the server's ``IndexData``).

    The server sends abbreviations only; the field names below follow them but their meaning was
    inferred from the abbreviation, not confirmed on a live frame. ``raw`` keeps the original
    dict, so nothing is lost if a name turns out different.

    Attributes:
        type: Message type.
        symbol: Index code (``s``), e.g. ``"VN30"``.
        board: Board code (``b``).
        status: Session status (``ss``).
        trading_time: Time of the event as the server sends it (``t``).
        value: Index value (``v``).
        change: Change against the reference (``c``).
        change_percent: Change in percent (``cr``).
        advances: Number of advancing stocks (``adv``).
        declines: Number of declining stocks (``dec``).
        no_change: Number of unchanged stocks (``nc``).
        ceilings: Number of stocks at the ceiling (``ce``).
        floors: Number of stocks at the floor (``fl``).
        total_match_value: Matched value (``tmv``).
        total_match_quantity: Matched quantity (``tmq``).
        total_put_value: Put-through value (``tvp``).
        total_put_quantity: Put-through quantity (``tqp``).
        total_quantity: Total quantity (``tq``).
        total_value: Total value (``tv``).
        raw: The frame's ``data`` object, untouched.
    """

    type: DataType = DataType.TRADE
    symbol: str = ""
    board: str = ""
    status: str = ""
    trading_time: str = ""
    value: int | float | None = None
    change: int | float | None = None
    change_percent: int | float | None = None
    advances: int | float | None = None
    declines: int | float | None = None
    no_change: int | float | None = None
    ceilings: int | float | None = None
    floors: int | float | None = None
    total_match_value: int | float | None = None
    total_match_quantity: int | float | None = None
    total_put_value: int | float | None = None
    total_put_quantity: int | float | None = None
    total_quantity: int | float | None = None
    total_value: int | float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> IndexTickMessage:
        """Build the message from the ``data`` object of a ``trade.index.<code>`` frame.

        Args:
            data: Payload with the abbreviated keys listed in the class attributes. Numbers may
                arrive as strings; a key the server omitted stays ``None``.
        """
        data = data if isinstance(data, dict) else {}
        return cls(
            symbol=str(data.get("s") or ""),
            board=str(data.get("b") or ""),
            status=str(data.get("ss") or ""),
            trading_time=str(data.get("t") or ""),
            value=_opt_number(data.get("v")),
            change=_opt_number(data.get("c")),
            change_percent=_opt_number(data.get("cr")),
            advances=_opt_number(data.get("adv")),
            declines=_opt_number(data.get("dec")),
            no_change=_opt_number(data.get("nc")),
            ceilings=_opt_number(data.get("ce")),
            floors=_opt_number(data.get("fl")),
            total_match_value=_opt_number(data.get("tmv")),
            total_match_quantity=_opt_number(data.get("tmq")),
            total_put_value=_opt_number(data.get("tvp")),
            total_put_quantity=_opt_number(data.get("tqp")),
            total_quantity=_opt_number(data.get("tq")),
            total_value=_opt_number(data.get("tv")),
            raw=dict(data),
        )


@dataclass
class IntervalMessage:
    """Real-time trade interval.

    Attributes:
        type: Message/FCO type.
        interval_time: Start time of the candle.
        trading_time: Time of the event as the server sends it.
        symbol: Ticker symbol.
        open: Opening price (``None`` if the server did not send it).
        high: Highest price.
        low: Lowest price.
        close: Closing/last price.
        volume: Traded volume.
    """

    type: DataType = DataType.TRADE
    interval_time: str = ""
    trading_time: str = ""
    symbol: str = ""
    open: int | float = 0
    high: int | float = 0
    low: int | float = 0
    close: int | float = 0
    volume: int = 0
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> IntervalMessage:
        """Build an IntervalMessage (OHLCV bar) from a streamed interval dict.

        Args:
            data: Raw bar with keys ``st`` (interval time), ``t`` (time), ``s`` (symbol),
                ``o``/``h``/``l``/``c`` (OHLC prices), ``v`` (volume).
        Returns:
            A populated IntervalMessage instance.
        """
        return cls(
            interval_time=data.get("st", ""),
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            open=to_number(data.get("o", 0)),
            high=to_number(data.get("h", 0)),
            low=to_number(data.get("l", 0)),
            close=to_number(data.get("c", 0)),
            volume=to_int(data.get("v", 0)),
            # raw=data,
        )


@dataclass
class QuoteMessage:
    """Real-time bid/ask quote update.

    Attributes:
        type: Message/FCO type.
        trading_time: Time of the event as the server sends it.
        symbol: Ticker symbol.
        bid_prices: Bid prices, best first.
        bid_volumes: Bid volumes, parallel to ``bid_prices``.
        ask_prices: Ask prices, best first.
        ask_volumes: Ask volumes, parallel to ``ask_prices``.
    """

    type: DataType = DataType.QUOTE
    trading_time: str = ""
    symbol: str = ""
    bid_prices: list[float] = field(default_factory=list)
    bid_volumes: list[int] = field(default_factory=list)
    ask_prices: list[float] = field(default_factory=list)
    ask_volumes: list[int] = field(default_factory=list)
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> QuoteMessage:
        """Build a QuoteMessage from a streamed bid/ask quote dict.

        Args:
            data: Raw quote with keys ``t`` (time), ``s`` (symbol), and ``bids``/``asks``
                lists of ``[price, volume]`` pairs.
        Returns:
            A populated QuoteMessage instance with prices and volumes split into parallel lists.
        """
        bid_prices, bid_volumes = _levels(data.get("bids"))
        ask_prices, ask_volumes = _levels(data.get("asks"))
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            bid_prices=bid_prices,
            bid_volumes=bid_volumes,
            ask_prices=ask_prices,
            ask_volumes=ask_volumes,
        )


@dataclass
class MarketStatusMessage:
    """Market status update (open, close, halted, etc.).

    Attributes:
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        trading_date: Trading date as the server formats it (varies by endpoint; see
            ``parse_date``).
    """

    market: str = ""
    status: str = ""
    trading_date: str = ""
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> MarketStatusMessage:
        """Build a MarketStatusMessage from a streamed market-status dict.

        Args:
            data: Status payload with keys ``market``, ``status``, ``tradingDate``.
        Returns:
            A populated MarketStatusMessage instance.
        """
        return cls(
            market=data.get("market", ""),
            status=data.get("status", ""),
            trading_date=data.get("tradingDate", ""),
            # raw=data,
        )


@dataclass
class MarketFlagMessage:
    """Market session flag (e.g. ATO, LO, ATC) broadcast on the ``market.flag`` topic.

    Attributes:
        board: Board code exactly as the server sends it: ``HOSE``, ``HNX``, ``UPCOM`` or ``DER``
            (derivatives; note: not the enum's ``DERIVATIVES``).
        trading_time: Time of the event as the server sends it.
        flag: Session flag as the server sends it (e.g. ``"ATO"``, ``"LO"``, ``"ATC"``).
    """

    board: str = ""
    trading_time: str = ""
    flag: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> MarketFlagMessage:
        """Build a MarketFlagMessage from a streamed session-flag dict.

        Args:
            data: Flag payload with keys ``b`` (board), ``t`` (trading time), ``f`` (flag).
        Returns:
            A populated MarketFlagMessage instance. ``flag`` is kept as the raw string because
            the API does not enumerate every session value.
        """
        return cls(
            board=data.get("b", ""),
            trading_time=data.get("t", ""),
            flag=data.get("f", ""),
        )


@dataclass
class IndexSummaryMessage:
    """Full summary of one index, from ``indexsummary.<code>`` (e.g. ``indexsummary.VN30``).

    The public documentation does not list the fields of this payload, so none are guessed:
    ``index`` comes from the topic and ``data`` keeps what the server sent, untouched. Read
    values with :meth:`get`, which tries several keys.

    Attributes:
        index: Index code from the topic, upper-case (e.g. ``"VN30"``); ``""`` if unknown.
        data: The server's payload as a dict.
    """

    index: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict, topic: str = "") -> IndexSummaryMessage:
        """Build the message from the ``data`` object and the frame's ``topic``.

        Args:
            data: The frame's ``data`` object (anything else counts as empty).
            topic: The frame's topic, e.g. ``"indexsummary.VN30"``.
        Returns:
            The message; the index code is the part of the topic after ``indexsummary.``.
        """
        prefix = "indexsummary."
        code = topic[len(prefix) :] if topic.lower().startswith(prefix) else ""
        return cls(index=code.upper(), data=dict(data) if isinstance(data, dict) else {})

    def get(self, *keys: str, default: Any = None) -> Any:
        """The first of ``keys`` present in ``data`` (``default`` if none is).

        Args:
            keys: Candidate field names, tried in order, e.g. ``get("indexValue", "value")``.
            default: Returned when no key is present.
        """
        for key in keys:
            if key in self.data:
                return self.data[key]
        return default


@dataclass
class MarketDataMessage:
    """Master data (ceiling / floor / reference price) for a symbol, from ``market.<symbol>``.

    Attributes:
        symbol: Ticker symbol.
        board: Exchange board: a ``Board``, or the raw string for an unknown board.
        trading_time: Time of the event as the server sends it.
        ceiling: Ceiling price of the day.
        floor: Floor price of the day.
        ref_price: Reference price of the day.
    """

    symbol: str = ""
    board: str = ""
    trading_time: str = ""
    ceiling: int | float | None = None
    floor: int | float | None = None
    ref_price: int | float | None = None

    @classmethod
    def from_dict(cls, data: dict) -> MarketDataMessage:
        """Build a MarketDataMessage from a streamed master-data dict.

        Args:
            data: Payload with ``s`` (symbol), ``b`` (board), ``t`` (time) and ``ce``/``fl``/
                ``ref`` (ceiling/floor/reference prices).
        Returns:
            A populated MarketDataMessage; a price the server omitted is ``None``.
        """
        return cls(
            symbol=data.get("s", ""),
            board=data.get("b", ""),
            trading_time=data.get("t", ""),
            ceiling=_opt_number(data.get("ce")),
            floor=_opt_number(data.get("fl")),
            ref_price=_opt_number(data.get("ref")),
        )


@dataclass
class ForeignRoomMessage:
    """Foreign room (foreign investor activity) data.

    Attributes:
        type: Message/FCO type.
        trading_time: Time of the event as the server sends it.
        symbol: Ticker symbol.
        total_room: Total foreign room.
        current_room: Remaining foreign room.
    """

    type: DataType = DataType.ROOM
    trading_time: str = ""
    symbol: str = ""
    total_room: int = 0
    current_room: int = 0
    buy_quantity: int = 0
    buy_value: int = 0
    sell_quantity: int = 0
    sell_value: int = 0
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> ForeignRoomMessage:
        """Build a ForeignRoomMessage from a streamed foreign-room dict.

        Args:
            data: Raw payload with keys ``t`` (time), ``s`` (symbol), ``tr`` (total room),
                ``cr`` (current room), ``bq``/``bv`` (buy qty/value), ``sq``/``sv``
                (sell qty/value).
        Returns:
            A populated ForeignRoomMessage instance.
        """
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            total_room=to_int(data.get("tr", 0)),
            current_room=to_int(data.get("cr", 0)),
            buy_quantity=to_int(data.get("bq", 0)),
            buy_value=to_int(data.get("bv", 0)),
            sell_quantity=to_int(data.get("sq", 0)),
            sell_value=to_int(data.get("sv", 0)),
            # raw=data,
        )


@dataclass
class PutMessage:
    """Put-through (deal) data.

    Attributes:
        type: Message/FCO type.
        trading_time: Time of the event as the server sends it.
        symbol: Ticker symbol.
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        quantity: Order quantity (shares/contracts).
    """

    type: DataType = DataType.PUT
    trading_time: str = ""
    symbol: str = ""
    price: float = 0.0
    quantity: int = 0
    total_quantity: int = 0
    total_value: int = 0
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> PutMessage:
        """Build a PutMessage (put-through deal) from a streamed dict.

        Args:
            data: Raw payload with keys ``t`` (time), ``s`` (symbol), ``p`` (price),
                ``q`` (quantity), ``tq`` (total quantity), ``tv`` (total value).
        Returns:
            A populated PutMessage instance.
        """
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            price=to_number(data.get("p", 0.0)),
            quantity=to_int(data.get("q", 0)),
            total_quantity=to_int(data.get("tq", 0)),
            total_value=to_int(data.get("tv", 0)),
            # raw=data,
        )


@dataclass
class OddLotMessage:
    """Odd-lot trade data.

    Attributes:
        type: Message/FCO type.
        trading_time: Time of the event as the server sends it.
        symbol: Ticker symbol.
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        quantity: Order quantity (shares/contracts).
        bid_prices: Bid prices, best first.
        bid_volumes: Bid volumes, parallel to ``bid_prices``.
        ask_prices: Ask prices, best first.
        ask_volumes: Ask volumes, parallel to ``ask_prices``.
    """

    type: DataType = DataType.ODD_LOT
    trading_time: str = ""
    symbol: str = ""
    price: int | float = 0
    quantity: int = 0
    bid_prices: list[float] = field(default_factory=list)
    bid_volumes: list[int] = field(default_factory=list)
    ask_prices: list[float] = field(default_factory=list)
    ask_volumes: list[int] = field(default_factory=list)
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> OddLotMessage:
        """Build an OddLotMessage from a streamed odd-lot dict.

        Args:
            data: Raw payload with keys ``t`` (time), ``s`` (symbol), ``p`` (price),
                ``q`` (quantity), and ``bids``/``asks`` lists of ``[price, volume]`` pairs.
        Returns:
            A populated OddLotMessage instance with prices and volumes split into parallel lists.
        """
        bid_prices, bid_volumes = _levels(data.get("bids"))
        ask_prices, ask_volumes = _levels(data.get("asks"))
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            price=to_number(data.get("p", 0)),
            quantity=to_int(data.get("q", 0)),
            bid_prices=bid_prices,
            bid_volumes=bid_volumes,
            ask_prices=ask_prices,
            ask_volumes=ask_volumes,
        )


@dataclass
class OrderStatusMessage:
    """Real-time order status update (``orderEvent`` on ``order.<account>``).

    Prices of ATO/ATC/MP orders are words, so ``price`` is a ``Decimal`` when numeric and
    the raw string otherwise. Besides the usual cycle an order can report ``PD`` (accepted,
    not yet at the exchange) and ``RJ`` (rejected by the server itself, with ``error_code``).

    Attributes:
        type: Message/FCO type.
        account_no: Trading account number.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        order_id: Server-assigned order id.
        symbol: Ticker symbol.
        side: Order side: an ``OrderSide``, or the raw string for an unknown value.
        order_type: Order type: an ``OrderType`` member, or the raw string for an unknown
            type.
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        quantity: Order quantity (shares/contracts).
        os_quantity: Outstanding quantity. The REST order book never sends it, so it is
            ``None`` there.
        filled_quantity: Matched quantity.
        cancel_quantity: Cancelled quantity.
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        input_time: When the order was entered, ``"yyyy/MM/dd HH:mm:ss"``.
        modified_time: When the order was last modified, ``"yyyy/MM/dd HH:mm:ss"``.
        message: Server message (for a rejection, the reason).
        avg_price: Average matched price.
        reject_reason: Why the order was rejected.
        system_request_id: Server-side request id.
        error_code: Server error code when the order was rejected.
        error_message: Server error text when the order was rejected.
        notify_id: Server notification id.
        connection_id: Id of the connection the request came from.
    """

    type: StreamingType = StreamingType.ORDER
    account_no: str = ""
    client_request_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide | str | None = None
    order_type: OrderType | str | None = None
    price: Decimal | str = Decimal(0)
    quantity: int = 0
    os_quantity: int = 0
    filled_quantity: int = 0
    cancel_quantity: int = 0
    status: OrderStatus | str | None = None
    input_time: str = ""
    modified_time: str = ""
    message: str = ""
    avg_price: Decimal | str = Decimal(0)
    reject_reason: str = ""
    system_request_id: str = ""
    error_code: str = ""
    error_message: str = ""
    notify_id: str = ""
    connection_id: str = ""

    modify_time = _deprecated_alias("modify_time", "modified_time")

    @classmethod
    def from_dict(cls, data: dict) -> OrderStatusMessage:
        """Build an OrderStatusMessage from a streamed camelCase order-update dict.

        Args:
            data: Raw payload with keys such as ``accountNo``, ``clientRequestId``, ``orderId``,
                ``symbol``, ``side``, ``orderType``, ``price``, ``avgPrice``, ``quantity``,
                ``osQty``, ``filledQty``, ``cancelQty``, ``orderStatus``, ``inputTime``,
                ``modifiedTime`` (``modifyTime`` is read as a fallback), ``rejectReason``,
                ``errorCode``, ``errorMessage``, ``systemRequestId``, ``notifyId``,
                ``connectionId``. Times are ``yyyy/MM/dd HH:mm:ss``.
        Returns:
            A populated OrderStatusMessage. Enum fields are members, or the raw string for a
            value this SDK does not know (never an exception); absent ones are ``None``.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            client_request_id=data.get("clientRequestId", ""),
            order_id=data.get("orderId", ""),
            symbol=data.get("symbol", ""),
            side=to_enum(OrderSide, data.get("side")),
            order_type=to_enum(OrderType, data.get("orderType")),
            price=to_decimal(data.get("price")),
            quantity=to_int(data.get("quantity")),
            os_quantity=to_int(data.get("osQty")),
            filled_quantity=to_int(data.get("filledQty")),
            cancel_quantity=to_int(data.get("cancelQty")),
            status=to_enum(OrderStatus, data.get("orderStatus")),
            input_time=data.get("inputTime", ""),
            modified_time=pick(data, "modifiedTime", "modifyTime", default=""),
            message=data.get("rejectReason", "") or "",
            avg_price=to_decimal(data.get("avgPrice")),
            reject_reason=data.get("rejectReason", "") or "",
            system_request_id=data.get("systemRequestId", "") or "",
            error_code=str(data.get("errorCode") or ""),
            error_message=data.get("errorMessage", "") or "",
            notify_id=str(data.get("notifyId") or ""),
            connection_id=str(data.get("connectionId") or ""),
        )


@dataclass
class OrderMatchMessage:
    """A fill of an order (``orderMatchEvent`` on ``order.<account>``).

    Attributes:
        type: Message/FCO type.
        notify_id: Server notification id.
        connection_id: Id of the connection the request came from.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        order_id: Server-assigned order id.
        symbol: Ticker symbol.
        side: Order side: an ``OrderSide``, or the raw string for an unknown value.
        account_no: Trading account number.
        match_price: Price of the fill.
        match_qty: Quantity of the fill.
        match_time: Time of the fill, ``"yyyy/MM/dd HH:mm:ss"``.
    """

    type: StreamingType = StreamingType.ORDER_MATCH
    notify_id: str = ""
    connection_id: str = ""
    client_request_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide | str | None = None
    account_no: str = ""
    match_price: Decimal | str = Decimal(0)
    match_qty: int = 0
    match_time: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> OrderMatchMessage:
        """Build an OrderMatchMessage from a streamed ``orderMatchEvent`` dict.

        Args:
            data: Payload with ``notifyId``, ``connectionId``, ``clientRequestId``,
                ``orderId``, ``symbol``, ``side``, ``accountNo``, ``matchPrice`` (a string),
                ``matchQty`` (a long) and ``matchTime``.
        Returns:
            A populated OrderMatchMessage; every field tolerates being absent.
        """
        return cls(
            notify_id=str(data.get("notifyId") or ""),
            connection_id=str(data.get("connectionId") or ""),
            client_request_id=data.get("clientRequestId", "") or "",
            order_id=data.get("orderId", "") or "",
            symbol=data.get("symbol", "") or "",
            side=to_enum(OrderSide, data.get("side")),
            account_no=data.get("accountNo", "") or "",
            match_price=to_decimal(data.get("matchPrice")),
            match_qty=to_int(data.get("matchQty")),
            match_time=data.get("matchTime", "") or "",
        )


@dataclass
class PortfolioMessage:
    """Real-time position update (``clientPortfolioEvent``, derivative accounts only).

    ``total_asset``, ``cash_balance`` and ``stock_value`` are deprecated: the server never
    sends them, so they stay ``None``.

    Attributes:
        type: Message/FCO type.
        account_no: Trading account number.
        symbol: Ticker symbol.
        long_qty: Long quantity.
        short_qty: Short quantity.
        net: Net position (may be negative).
        market_price: Current market price.
        floating_pl: Floating profit/loss.
        trading_pl: Realised trading profit/loss.
        position_type: Type of the position as the server reports it.
    """

    type: StreamingType = StreamingType.PORTFOLIO
    account_no: str = ""
    total_asset: float | None = None
    cash_balance: float | None = None
    stock_value: float | None = None
    symbol: str = ""
    long_qty: int = 0
    short_qty: int = 0
    net: int = 0
    bid_avg_price: float | None = None
    ask_avg_price: float | None = None
    trade_price: float | None = None
    market_price: float | None = None
    floating_pl: float | None = None
    trading_pl: float | None = None
    position_type: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> PortfolioMessage:
        """Build a PortfolioMessage from a streamed camelCase portfolio-update dict.

        Args:
            data: Payload with ``accountNo``, ``symbol``, ``longQty``, ``shortQty``, ``net``
                (may be negative), ``bidAvgPrice``, ``askAvgPrice``, ``tradePrice``,
                ``marketPrice``, ``floatingPL``, ``tradingPL`` and ``positionType``.
        Returns:
            A populated PortfolioMessage; a price the server omitted is ``None``.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            total_asset=to_opt_float(data.get("totalAsset")),
            cash_balance=to_opt_float(data.get("cashBalance")),
            stock_value=to_opt_float(data.get("stockValue")),
            symbol=data.get("symbol", "") or "",
            long_qty=to_int(data.get("longQty")),
            short_qty=to_int(data.get("shortQty")),
            net=to_int(data.get("net")),
            bid_avg_price=to_opt_float(data.get("bidAvgPrice")),
            ask_avg_price=to_opt_float(data.get("askAvgPrice")),
            trade_price=to_opt_float(data.get("tradePrice")),
            market_price=to_opt_float(data.get("marketPrice")),
            floating_pl=to_opt_float(data.get("floatingPL")),
            trading_pl=to_opt_float(data.get("tradingPL")),
            position_type=str(data.get("positionType") or ""),
        )


@dataclass
class FCOOrderUpdateMessage:
    """Real-time order status update (portfolio streaming).

    Attributes:
        fco_id: Id of the conditional order.
        process_status: Processing status of the conditional order.
        matched_quantity: Quantity matched so far.
        is_place_order: Whether the conditional order has already placed its order.
        symbol: Ticker symbol.
        quantity: Order quantity (shares/contracts).
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        account_no: Trading account number.
        updated_time: When the entry was last updated.
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        message: Server message (for a rejection, the reason).
        username: User the event belongs to.
        event_type: Event type reported by the server.
        type: Message/FCO type.
    """

    fco_id: str = ""
    process_status: FCOStatus | str | None = None
    matched_quantity: int = 0
    is_place_order: bool = False
    symbol: str = ""
    quantity: int = 0
    price: str = ""
    account_no: str = ""
    updated_time: str = ""
    status: str = ""
    message: str = ""
    username: str = ""
    event_type: str = ""
    type: FCOType | str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> FCOOrderUpdateMessage:
        """Build FCOOrderUpdateMessage from a streamed camelCase order-update dict.

        Args:
            data: Raw payload with keys ``fcoId``, ``processStatus``, ``matchedQuantity``,
                ``isPlaceOrder``, ``symbol``, ``quantity``, ``price``, ``accountNo``,
                ``updatedTime``, ``status``, ``message``, ``username``, ``eventType``,
                ``type``, ``order``, ``attachedOrder``.
        Returns:
            A populated FCOOrderUpdateMessage instance.
        """
        common = parse_fco_common(data)
        return cls(
            fco_id=common["fco_id"],
            process_status=to_enum(FCOStatus, data.get("processStatus")),
            matched_quantity=common["matched_quantity"],
            is_place_order=common["is_place_order"],
            symbol=common["symbol"],
            quantity=common["quantity"],
            price=data.get("price", 0),
            account_no=common["account_no"],
            updated_time=data.get("updatedTime", ""),
            status=data.get("status", ""),
            message=data.get("message", ""),
            username=data.get("username", ""),
            event_type=data.get("eventType", ""),
            type=common["type"],
        )


# What ``on_data`` / ``on_trading`` receive. A frame whose topic or event type this SDK has no model
# for arrives as the raw ``dict`` (see the ``isinstance`` checks in the README, section 6.0).
DataMessage = (
    TradeMessage
    | IndexTickMessage
    | IntervalMessage
    | QuoteMessage
    | ForeignRoomMessage
    | MarketFlagMessage
    | IndexSummaryMessage
    | MarketDataMessage
    | MarketStatusMessage
    | PutMessage
    | OddLotMessage
    | dict[str, Any]
)
TradingMessage = (
    OrderStatusMessage
    | OrderMatchMessage
    | PortfolioMessage
    | FCOOrderUpdateMessage
    | dict[str, Any]
)
