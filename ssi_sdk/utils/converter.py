"""Type conversion utilities."""

from __future__ import annotations

from typing import Any

from ssi_sdk.enums import OrderSide


def to_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float.

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        The converted float, or default if conversion fails.
    """
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int.

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        The converted int, or default if conversion fails.
    """
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def to_number(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to a number (float or int).

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        The converted number, or default if conversion fails.
    """
    try:
        if value is None:
            return default
        num = float(value)
        # Convert to int if decimal part is .0
        if num == int(num):
            return int(num)
        return num
    except (ValueError, TypeError):
        return default


def to_price(value) -> int | float | OrderSide:
    """Parse price: returns numeric if possible, otherwise OrderSide enum."""
    if value is None:
        return 0
    try:
        num = float(value)
        return int(num) if num == int(num) else num
    except (ValueError, TypeError):
        try:
            return OrderSide(value)
        except ValueError:
            return 0
