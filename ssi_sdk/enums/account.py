"""Enums for SSI API."""

from ssi_sdk.enums.base import BaseEnum


class AccountType(BaseEnum):
    """Account type as the server names it (``accountType``).

    Members:
        ``EQUITY``: ``"Cash"`` cash equity account.
        ``EQUITY_MARGIN``: ``"Margin"`` margin equity account.
        ``DERIVATIVE``: ``"Derivative"`` derivatives account.
    """

    EQUITY = "Cash"
    EQUITY_MARGIN = "Margin"
    DERIVATIVE = "Derivative"
