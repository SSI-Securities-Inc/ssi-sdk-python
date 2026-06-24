"""Trading enum for SSI."""

from enum import Enum


class OrderSide(Enum):
    """Enum representing order sides for SSI."""

    BUY = "B"
    SELL = "S"


class OrderType(Enum):
    """Enum representing different order types for SSI."""

    ATO = "ATO"
    ATC = "ATC"
    LO = "LO"
    MTL = "MTL"
    MP = "MP"
    MOK = "MOK"
    MAK = "MAK"
    PLO = "PLO"


class OrderStatus(Enum):
    """Enum representing order statuses for SSI."""

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
