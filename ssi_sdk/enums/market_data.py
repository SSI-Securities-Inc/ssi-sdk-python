"""Enums for SSI API."""

from ssi_sdk.enums.base import BaseEnum


class Board(BaseEnum):
    """Enum representing different stock exchange boards."""

    HOSE = "HOSE"
    HNX = "HNX"
    UPCOM = "UPCOM"
    DERIVATIVES = "DERIVATIVES"
