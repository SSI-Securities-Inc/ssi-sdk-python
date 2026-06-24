"""Streaming enum for SSI."""

from enum import Enum


class StreamingMethod(Enum):
    """Enum representing different streaming methods for SSI."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING_PONG = "ping_pong"
    LIST_SUBSCRIPTION = "list_subscription"


class StreamingChannel(Enum):
    """Enum representing different streaming channels for SSI."""

    DATA = "DATA"
    HEARTBEAT = "HEARTBEAT"
    TRADING = "TRADING"


class StreamingType(Enum):
    """Enum representing different streaming types for SSI."""

    ORDER = "orderEvent"
    ORDER_MATCH = "orderMatchEvent"
    PORTFOLIO = "clientPortfolioEvent"


class DataTopic(Enum):
    """Enum representing different data topics for SSI."""

    QUOTE = "quote."
    TRADE = "trade."
    ODD_LOT = "oddlot."
    MARKET = "market."
    ROOM = "room."
    PUT = "put."


class DataType(Enum):
    """Enum representing different data types for SSI."""

    QUOTE = "quote"
    TRADE = "trade"
    ODD_LOT = "oddlot"
    MARKET = "market"
    ROOM = "room"
    PUT = "put"
