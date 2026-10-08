"""Streaming enum for SSI."""

from ssi_sdk.enums.base import BaseEnum


class StreamingMethod(BaseEnum):
    """Request methods (the server compares them case-insensitively).

    Members:
        ``SUBSCRIBE``: Add topics.
        ``UNSUBSCRIBE``: Remove topics.
        ``PING_PONG``: Ask for a ``pong`` ack.
        ``LIST_SUBSCRIPTION``: List the topics subscribed on this connection.
    """

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING_PONG = "ping_pong"
    LIST_SUBSCRIPTION = "list_subscription"


class StreamingChannel(BaseEnum):
    """Channels of the stream.

    Members:
        ``DATA``: Market data topics (trade, quote, room, market, ...).
        ``TRADING``: Account events (``order.*``, ``portfolio.*``).
        ``HEARTBEAT``: Ping/pong acknowledgements.
    """

    DATA = "DATA"
    HEARTBEAT = "HEARTBEAT"
    TRADING = "TRADING"


class StreamingType(BaseEnum):
    """``data.eventType`` of trading events.

    Members:
        ``ORDER``: ``orderEvent``: an order changed status.
        ``ORDER_MATCH``: ``orderMatchEvent``: a fill.
        ``PORTFOLIO``: ``clientPortfolioEvent``: a derivative position update.
    """

    ORDER = "orderEvent"
    ORDER_MATCH = "orderMatchEvent"
    PORTFOLIO = "clientPortfolioEvent"


class DataTopic(BaseEnum):
    """Enum representing different data topics for SSI."""

    QUOTE = "quote."
    TRADE = "trade."
    ODD_LOT = "oddlot."
    MARKET = "market."
    INDEX_SUMMARY = "indexsummary."
    ROOM = "room."
    PUT = "put."


class DataType(BaseEnum):
    """Enum representing different data types for SSI."""

    QUOTE = "quote"
    TRADE = "trade"
    ODD_LOT = "oddlot"
    MARKET = "market"
    ROOM = "room"
    PUT = "put"
    INDEX_SUMMARY = "indexsummary"
