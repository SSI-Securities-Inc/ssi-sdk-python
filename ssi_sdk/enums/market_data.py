"""Enums for SSI API."""

from ssi_sdk.enums.base import BaseEnum


class Board(BaseEnum):
    """Exchange board.

    Members:
        ``HOSE``: Ho Chi Minh Stock Exchange.
        ``HNX``: Hanoi Stock Exchange.
        ``UPCOM``: UPCoM market.
        ``DERIVATIVES``: Derivatives; only valid on the stream and master data, not on the REST
            data endpoints.
    """

    HOSE = "HOSE"
    HNX = "HNX"
    UPCOM = "UPCOM"
    DERIVATIVES = "DERIVATIVES"
