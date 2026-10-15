"""Trading enum for SSI."""

from ssi_sdk.enums.base import BaseEnum


class OrderSide(BaseEnum):
    """Side of an order.

    Members:
        ``BUY``: ``"B"`` buy.
        ``SELL``: ``"S"`` sell.
    """

    BUY = "B"
    SELL = "S"


class OrderType(BaseEnum):

    """Order type.

    ``price`` is required for ``LO``/``PLO`` and ignored by market-priced types.

    Members:
        ``LO``: Limit order at ``price``.
        ``ATO``: At-the-open: matched in the opening auction.
        ``ATC``: At-the-close: matched in the closing auction.
        ``MTL``: Market-to-limit (HOSE): market order whose unfilled part becomes a limit order.
        ``MP``: Market price (HNX/UPCOM).
        ``MOK``: Match-or-kill (HNX): fill completely at once or cancel.
        ``MAK``: Match-and-kill (HNX): fill what is possible at once, cancel the rest.
        ``PLO``: Post-close limit order, traded in the session after the closing auction.
    """

    ATO = "ATO"
    ATC = "ATC"
    LO = "LO"
    MTL = "MTL"
    MP = "MP"
    MOK = "MOK"
    MAK = "MAK"
    PLO = "PLO"


class OrderStatus(BaseEnum):
    """Order status as the servers report it.

    Descriptions follow the code names; the server docs do not define every code, so always
    keep unknown values as the raw string.

    Members:
        ``PENDING``: ``PD`` accepted, not yet processed.
        ``PENDING_APPROVAL``: ``WA`` waiting for approval.
        ``READY``: ``RS`` ready to be sent.
        ``SENT``: ``SD`` sent to the exchange.
        ``QUEUED``: ``QU`` resting in the order book.
        ``FILLED``: ``FF`` fully filled.
        ``PARTIAL_FILLED``: ``PF`` partially filled.
        ``PARTIAL_CANCELLED``: ``FFPC`` partially filled, remainder cancelled.
        ``PENDING_MODIFY``: ``WM`` waiting for a modification to be confirmed.
        ``PENDING_CANCEL``: ``WC`` waiting for a cancellation to be confirmed.
        ``CANCELLED``: ``CL`` cancelled.
        ``REJECTED``: ``RJ`` rejected (by the server or the exchange).
        ``EXPIRED``: ``EX`` expired.
        ``PRE_SESSION``: ``IAV`` waiting for its session.
        ``SOI``: ``SOI`` reported by the order engine.
        ``PAS``: ``PAS`` reported by the order engine.
        ``CPL``: ``CPL`` reported by the order engine.
        ``REQUESTED``: ``RQ`` request received (FCO engine).
        ``ERROR``: ``ERR`` error reported by the engine.
    """

    PENDING = "PD"
    PENDING_APPROVAL = "WA"
    READY = "RS"
    SENT = "SD"
    QUEUED = "QU"
    FILLED = "FF"
    PARTIAL_FILLED = "PF"
    PARTIAL_CANCELLED = "FFPC"
    PENDING_MODIFY = "WM"
    PENDING_CANCEL = "WC"
    CANCELLED = "CL"
    REJECTED = "RJ"
    EXPIRED = "EX"
    PRE_SESSION = "IAV"
    # Reported by the order/FCO engines; named after their codes.
    SOI = "SOI"
    PAS = "PAS"
    CPL = "CPL"
    REQUESTED = "RQ"
    ERROR = "ERR"
