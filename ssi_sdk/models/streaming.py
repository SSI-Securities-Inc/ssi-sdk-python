"""Streaming message models (real-time data via WebSocket)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ssi_sdk.enums import (
    DataType,
    OrderSide,
    OrderStatus,
    OrderType,
    StreamingChannel,
    StreamingMethod,
    StreamingType,
    FCOType,
    FCOStatus,
)
from ssi_sdk.utils import to_int, to_number


@dataclass
class RequestMessage:
    """Message format for subscribing/unsubscribing to streaming channels."""

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
    """Heartbeat message from the server."""

    method: StreamingMethod | str = ""
    channel: StreamingChannel | str = ""
    status: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> HeartbeatMessage:
        """Build a HeartbeatMessage from a server message dict.

        Args:
            data: Heartbeat payload with ``method``, ``channel``, ``status``, ``message`` keys.
        Returns:
            A populated HeartbeatMessage instance.
        """
        method = StreamingMethod(data.get("method", "")) if data.get("method") else ""
        channel = StreamingChannel(data.get("channel", "")) if data.get("channel") else ""
        return cls(
            method=method,
            channel=channel,
            status=data.get("status", ""),
            message=data.get("message", ""),
        )


@dataclass
class TradeMessage:
    """Real-time trade tick."""

    type: DataType = DataType.TRADE
    trading_time: str = ""
    symbol: str = ""
    price: int | float = 0
    quantity: int = 0
    side: str = ""
    total_volume: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> TradeMessage:
        """Build a TradeMessage from a streamed trade-tick dict.

        Args:
            data: Raw tick with keys ``t`` (time), ``s`` (symbol), ``p`` (price), ``q``
                (quantity), ``si`` (side), ``v`` (total volume).
        Returns:
            A populated TradeMessage instance, defaulting ``side`` to ``"U"`` when absent.
        """
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            price=to_number(data.get("p", 0.0)),
            quantity=to_int(data.get("q", 0)),
            side=data.get("si", "") if data.get("si", "") else "U",
            total_volume=to_int(data.get("v", 0)),
        )


@dataclass
class IntervalMessage:
    """Real-time trade interval."""

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
    """Real-time bid/ask quote update."""

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
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            bid_prices=[to_number(i[0]) for i in data.get("bids", [])],
            bid_volumes=[to_int(i[1]) for i in data.get("bids", [])],
            ask_prices=[to_number(i[0]) for i in data.get("asks", [])],
            ask_volumes=[to_int(i[1]) for i in data.get("asks", [])],
            # raw=data,
        )


@dataclass
class MarketStatusMessage:
    """Market status update (open, close, halted, etc.)."""

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
class ForeignRoomMessage:
    """Foreign room (foreign investor activity) data."""

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
    """Put-through (deal) data."""

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
    """Odd-lot trade data."""

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
        return cls(
            trading_time=data.get("t", ""),
            symbol=data.get("s", ""),
            price=to_number(data.get("p", 0)),
            quantity=to_int(data.get("q", 0)),
            bid_prices=[to_number(i[0]) for i in data.get("bids", [])],
            bid_volumes=[to_int(i[1]) for i in data.get("bids", [])],
            ask_prices=[to_number(i[0]) for i in data.get("asks", [])],
            ask_volumes=[to_int(i[1]) for i in data.get("asks", [])],
            # raw=data,
        )


@dataclass
class OrderStatusMessage:
    """Real-time order status update (portfolio streaming)."""

    type: StreamingType = StreamingType.ORDER
    account_no: str = ""
    client_request_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide | None = None
    order_type: OrderType | None = None
    price: int | float | OrderSide = 0
    quantity: int = 0
    os_quantity: int = 0
    filled_quantity: int = 0
    cancel_quantity: int = 0
    status: OrderStatus | None = None
    input_time: str = ""
    modify_time: str = ""
    message: str = ""
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> OrderStatusMessage:
        """Build an OrderStatusMessage from a streamed camelCase order-update dict.

        Args:
            data: Raw payload with keys such as ``accountNo``, ``clientRequestId``, ``orderId``,
                ``symbol``, ``side``, ``orderType``, ``price``, ``quantity``, ``osQty``,
                ``filledQty``, ``cancelQty``, ``orderStatus``, ``inputTime``, ``modifyTime``,
                ``rejectReason``.
        Returns:
            A populated OrderStatusMessage instance with enum fields left as ``None`` when absent.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            client_request_id=data.get("clientRequestId", ""),
            order_id=data.get("orderId", ""),
            symbol=data.get("symbol", ""),
            side=OrderSide(data["side"]) if data.get("side") else None,
            order_type=OrderType(data["orderType"]) if data.get("orderType") else None,
            price=data.get("price", 0),
            quantity=data.get("quantity", 0),
            os_quantity=data.get("osQty", 0),
            filled_quantity=data.get("filledQty", 0),
            cancel_quantity=data.get("cancelQty", 0),
            status=OrderStatus(data["orderStatus"]) if data.get("orderStatus") else None,
            input_time=data.get("inputTime", ""),
            modify_time=data.get("modifyTime", ""),
            message=data.get("rejectReason", ""),
            # raw=data,
        )


@dataclass
class PortfolioMessage:
    """Real-time portfolio update."""

    type: StreamingType = StreamingType.PORTFOLIO
    account_no: str = ""
    total_asset: float = 0.0
    cash_balance: float = 0.0
    stock_value: float = 0.0
    # raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> PortfolioMessage:
        """Build a PortfolioMessage from a streamed camelCase portfolio-update dict.

        Args:
            data: Raw payload with keys ``accountNo``, ``totalAsset``, ``cashBalance``,
                ``stockValue``.
        Returns:
            A populated PortfolioMessage instance.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            total_asset=data.get("totalAsset", 0.0),
            cash_balance=data.get("cashBalance", 0.0),
            stock_value=data.get("stockValue", 0.0),
            # raw=data,
        )

@dataclass
class FCOOrderUpdateMessage:
    """Real-time order status update (portfolio streaming)."""

    fco_id: str = ""
    process_status: FCOStatus | None = None
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
    type: FCOType | None = None

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
        return cls(
            fco_id=data.get("fcoId", ""),
            process_status=FCOStatus(data["processStatus"]) if data.get("processStatus") else None,
            matched_quantity=data.get("matchedQuantity", 0),
            is_place_order=data.get("isPlaceOrder", False),
            symbol=data.get("symbol", ""),
            quantity=data.get("quantity", 0),
            price=data.get("price", 0),
            account_no=data.get("accountNo", ""),
            updated_time=data.get("updatedTime", ""),
            status=data.get("status", ""),
            message=data.get("message", ""),
            username=data.get("username", ""),
            event_type=data.get("eventType", ""),
            type=FCOType(data["type"]) if data.get("type") else None,
        )
