"""Enums for SSI API."""

from enum import Enum


class AccountType(Enum):
    """Enum representing different account types."""

    EQUITY = "Cash"
    EQUITY_MARGIN = "Margin"
    DERIVATIVE = "Derivative"
