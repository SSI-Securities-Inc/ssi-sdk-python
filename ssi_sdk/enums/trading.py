"""Trading enum for SSI."""

from ssi_sdk.enums.base import BaseEnum


class OrderSide(BaseEnum):
    """Enum representing order sides for SSI."""

    BUY = "B"
    SELL = "S"


class OrderType(BaseEnum):

    """Enum representing different order types for SSI."""

    ATO = "ATO"
    ATC = "ATC"
    LO = "LO"
    MTL = "MTL"
    MP = "MP"
    MOK = "MOK"
    MAK = "MAK"
    PLO = "PLO"


class OrderStatus(BaseEnum):
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
