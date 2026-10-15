"""Input validation utilities."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from ssi_sdk.exceptions import ValidationError


def require_non_empty(value: Any, field_name: str) -> Any:
    """Validate that a value is present: not None, not an empty or blank string/collection.

    ``0`` and ``False`` count as present; range checks belong to ``require_positive`` and
    friends, not here.

    Args:
        value: The value to check.
        field_name: Name of the field (for error messages).

    Returns:
        The validated value.

    Raises:
        ValidationError: If value is None, blank, or an empty collection.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{field_name} is required and cannot be empty")
    if hasattr(value, "__len__") and len(value) == 0:
        raise ValidationError(f"{field_name} is required and cannot be empty")
    return value


def require_empty(value: str | None, field_name: str) -> None:
    """Validate that a string is None or empty.

    Args:
        value: The value to check.
        field_name: Name of the field (for error messages).
    Raises:
        ValidationError: If value is not None or empty.
    """
    if value:
        raise ValidationError(f"{field_name} must be empty or None, got '{value}'")
    return value


def require_positive(value: int | float | Decimal, field_name: str) -> int | float | Decimal:
    """Validate that a number is positive.

    Args:
        value: The value to check.
        field_name: Name of the field (for error messages).

    Returns:
        The validated positive number.

    Raises:
        ValidationError: If value is not positive.
    """
    if value <= 0:
        raise ValidationError(f"{field_name} must be positive, got {value}")
    return value


def require_non_negative(
    value: int | float | Decimal, field_name: str
) -> int | float | Decimal:
    """Validate that a number is non-negative.

    Args:
        value: The value to check.
        field_name: Name of the field (for error messages).
    Returns:
        The validated non-negative number.
    Raises:
        ValidationError: If value is negative.
    """
    if value < 0:
        raise ValidationError(f"{field_name} must be non-negative, got {value}")
    return value


def require_in(value: str, allowed: set[str], field_name: str) -> str:
    """Validate that a string is in an allowed set.

    Args:
        value: The value to check.
        allowed: Set of allowed values.
        field_name: Name of the field (for error messages).

    Returns:
        The validated value.

    Raises:
        ValidationError: If value is not in the allowed set.
    """
    if value not in allowed:
        raise ValidationError(f"{field_name} must be one of {sorted(allowed)}, got '{value}'")
    return value


_SYMBOL_RE = re.compile(r"[A-Za-z0-9]+")
_DATE_FORMAT = "%Y/%m/%d"
_DATETIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def require_symbol(value: str | None, field_name: str = "symbol") -> str:
    """Validate a single alphanumeric ticker symbol (no lists, no separators).

    Args:
        value: The value to check.
        field_name: Name of the field (for error messages).
    Returns:
        The validated symbol.
    Raises:
        ValidationError: If value is empty or contains anything but letters and digits.
    """
    require_non_empty(value, field_name)
    if not _SYMBOL_RE.fullmatch(value):
        raise ValidationError(f"{field_name} must be a single alphanumeric symbol, got '{value}'")
    return value


def parse_date_arg(
    value: str, field_name: str, *, allow_time: bool = False, time_required: bool = False
) -> datetime:
    """Parse a ``YYYY/MM/DD`` (optionally ``YYYY/MM/DD HH:MM:SS``) request date.

    Args:
        value: The date string.
        field_name: Name of the field (for error messages).
        allow_time: Also accept the ``YYYY/MM/DD HH:MM:SS`` layout.
        time_required: Accept only the ``YYYY/MM/DD HH:MM:SS`` layout (as FCO dates need).
    Returns:
        The parsed datetime (midnight for a date-only value).
    Raises:
        ValidationError: If the value does not match an accepted layout.
    """
    require_non_empty(value, field_name)
    if time_required:
        formats: tuple[str, ...] = (_DATETIME_FORMAT,)
    else:
        formats = (_DATE_FORMAT, _DATETIME_FORMAT) if allow_time else (_DATE_FORMAT,)
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    if time_required:
        expected = "YYYY/MM/DD HH:MM:SS"
    else:
        expected = "YYYY/MM/DD HH:MM:SS or YYYY/MM/DD" if allow_time else "YYYY/MM/DD"
    raise ValidationError(f"{field_name} must be formatted {expected}, got '{value}'")


def require_date_range(
    from_date: str,
    to_date: str,
    *,
    allow_time: bool = False,
    time_required: bool = False,
    max_days: int | None = None,
) -> None:
    """Validate a ``from``/``to`` pair: both well formed, ``from <= to``, optional span cap.

    Args:
        from_date: Range start.
        to_date: Range end.
        allow_time: Also accept the ``YYYY/MM/DD HH:MM:SS`` layout.
        time_required: Accept only the ``YYYY/MM/DD HH:MM:SS`` layout.
        max_days: Maximum allowed span in days, if the endpoint has one.
    Raises:
        ValidationError: On a malformed date, ``from > to``, or a span above ``max_days``.
    """
    start = parse_date_arg(from_date, "from", allow_time=allow_time, time_required=time_required)
    end = parse_date_arg(to_date, "to", allow_time=allow_time, time_required=time_required)
    if start > end:
        raise ValidationError(f"from must not be after to ({from_date} > {to_date})")
    if max_days is not None and end - start > timedelta(days=max_days):
        raise ValidationError(f"date range must not exceed {max_days} days")


def require_exactly_one(first: object, second: object, first_name: str, second_name: str) -> None:
    """Validate that exactly one of two optional arguments was given (XOR).

    Raises:
        ValidationError: If both or neither is set.
    """
    if bool(first) == bool(second):
        raise ValidationError(f"exactly one of {first_name} or {second_name} is required")
