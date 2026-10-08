"""FCO enum for SSI."""

from typing import Literal

from ssi_sdk.enums.base import BaseEnum


class FCOType(BaseEnum):
    """Flexible conditional order (FCO) type.

    Members:
        ``GTD``: Good-till-date order placed with a validity window.
        ``STOP``: Stop (market) order fired by ``stop_price``.
        ``STOP_LIMIT``: Stop-limit order: fired by ``stop_price``, then a limit order.
        ``TRAILING_STOP``: Trailing stop (market).
        ``TRAILING_STOP_LIMIT``: Trailing stop with a limit order.
        ``OCO``: One-cancels-the-other: a take-profit and a stop-loss leg.
        ``BULL_BEAR``: Bull/bear: an entry order with take-profit and stop-loss legs.
    """

    GTD = "gtd"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    TRAILING_STOP_LIMIT = "trailing_stop_limit"
    OCO = "oco"
    BULL_BEAR = "bullbear"

class FCOOperator(BaseEnum):
    """Comparison that fires an FCO trigger.

    Requests send the name; responses may give the number 0..4.

    Members:
        ``GREATER``: price > trigger (response number 2).
        ``GREATER_OR_EQUAL``: price >= trigger (0).
        ``LESSER``: price < trigger (3).
        ``LESSER_OR_EQUAL``: price <= trigger (4).
        ``EQUAL``: price == trigger (1).
    """

    GREATER = "greater"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESSER = "lesser"
    LESSER_OR_EQUAL = "lesser_or_equal"
    EQUAL = "equal"

class FCOStatus(BaseEnum):
    """Processing status of an FCO.

    Descriptions are inferred from the code names; keep unknown values as raw strings.

    Members:
        ``INIT``: Created.
        ``WAIT``: Waiting for its trigger.
        ``TRI``: Triggered.
        ``TRIT``: Triggered, its order(s) in progress.
        ``TER``: Terminated.
        ``FIS``: Finished.
        ``WC``: Waiting for cancellation.
        ``EXP``: Expired.
        ``ERR``: Error.
    """
    INIT = "INIT"
    WAIT = "WAIT"
    TRI = "TRI"
    TRIT = "TRIT"
    TER = "TER"
    FIS = "FIS"
    WC = "WC"
    EXP = "EXP"
    ERR = "ERR"


# What a parameter may be given: the enum member, or its string (the Literals let an IDE suggest
# the valid strings).
FCOStatusLike = FCOStatus | Literal["INIT", "WAIT", "TRI", "TRIT", "TER", "FIS", "WC", "EXP", "ERR"]
FCOTypeLike = FCOType | Literal[
    "gtd", "stop", "stop_limit", "trailing_stop", "trailing_stop_limit", "oco", "bullbear"
]
FCOOperatorLike = FCOOperator | Literal[
    "greater", "greater_or_equal", "lesser", "lesser_or_equal", "equal"
]
