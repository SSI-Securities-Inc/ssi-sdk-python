"""FCO enum for SSI."""

from ssi_sdk.enums.base import BaseEnum


class FCOType(BaseEnum):
    """Enum representing FCO types for SSI."""

    GTD = "gtd"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    TRAILING_STOP_LIMIT = "trailing_stop_limit"
    OCO = "oco"
    BULL_BEAR = "bullbear"

class FCOOperator(BaseEnum):
    """Enum representing FCO operators for SSI."""

    GREATER = "greater"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESSER = "lesser"
    LESSER_OR_EQUAL = "lesser_or_equal"
    EQUAL = "equal"

class FCOStatus(BaseEnum):
    """ Enum representing FCO status for SSI."""
    INIT = "INIT"
    WAIT = "WAIT"
    TRI = "TRI"
    TRIT = "TRIT"
    TER = "TER"
    FIS = "FIS"
    WC = "WC"
    EXP = "EXP"
    ERR = "ERR"
