"""Type conversion utilities."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, overload

from ssi_sdk.enums import OrderType
from ssi_sdk.exceptions import ValidationError

# Server "no data" marker: HTTP 200 with ``{"code": 204, "msg": "No Content"}``.
_NO_CONTENT_CODE = "204"

# Date layouts the server is known to emit, tried in order. ``%m/%d/%Y`` precedes
# ``%d/%m/%Y`` so an ambiguous value like 01/02/2025 reads as MM/DD/YYYY.
_DATE_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
)


def _to_decimal_or_none(value: Any) -> Decimal | None:
    """Parse a finite Decimal from a number or numeric string; None when impossible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        number = value
    else:
        try:
            number = Decimal(str(value).strip().replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
    return number if number.is_finite() else None


def to_enum(enum_cls: Any, value: Any) -> Any:
    """Convert to an enum member, keeping the raw value when it is not a known member.

    Args:
        enum_cls: A ``BaseEnum`` subclass.
        value: Raw value from the server.
    Returns:
        The member, the original value when unknown, or None when ``value`` is None/"".
    """
    if value is None or value == "":
        return None
    return enum_cls.from_value(value) or value


def pick(data: dict, *keys: str, default: Any = None) -> Any:
    """Return the first value among ``keys`` that is present and not None.

    Args:
        data: Source mapping.
        *keys: Candidate keys in priority order (e.g. server key, then legacy key).
        default: Value returned when no key yields a non-None value.
    Returns:
        The first non-None value, or ``default``.
    """
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def is_no_content(body: Any) -> bool:
    """Whether a response body is the server's ``{"code": 204}`` empty-result marker.

    Args:
        body: Parsed response body.
    Returns:
        True when ``body`` is a dict whose ``code`` is 204.
    """
    return isinstance(body, dict) and str(body.get("code")) == _NO_CONTENT_CODE


def to_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float.

    Accepts thousands separators (``"2,493,089.5"``); inf/nan are rejected.

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        The converted float, or default if conversion fails.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, float):
        return value if math.isfinite(value) else default
    number = _to_decimal_or_none(value)
    return float(number) if number is not None else default


def to_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int.

    Accepts the string shapes the server emits for numbers: ``"1234.0"``,
    ``"2,493,089"``, ``"-3"``. The fraction is truncated toward zero.

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        The converted int, or default if the value is missing, a bool, or not finite.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    number = _to_decimal_or_none(value)
    return int(number) if number is not None else default


def to_opt_int(value: Any) -> int | None:
    """Convert to int, returning None (not 0) when the value is missing or invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = _to_decimal_or_none(value)
    return int(number) if number is not None else None


def to_opt_float(value: Any) -> float | None:
    """Convert to float, returning None (not 0.0) when the value is missing or invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = _to_decimal_or_none(value)
    return float(number) if number is not None else None


def to_decimal(value: Any) -> Decimal | Any:
    """Convert a price-like value to Decimal, keeping un-parsable values verbatim.

    Args:
        value: Number, numeric string, or a non-numeric marker such as ``"ATO"``.
    Returns:
        A finite Decimal; ``Decimal(0)`` for None/empty; otherwise the original
        value so a stream message never loses a field the SDK cannot parse.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal(0)
    if isinstance(value, bool):
        return value
    number = _to_decimal_or_none(value)
    return number if number is not None else value


@overload
def to_price_decimal(value: None) -> None: ...


@overload
def to_price_decimal(value: Any) -> Decimal: ...


def to_price_decimal(value: Any) -> Decimal | None:
    """Normalize a caller-supplied price to Decimal (via ``str`` so 0.1 stays 0.1).

    Args:
        value: Decimal, int, float, numeric string, or None.
    Returns:
        The Decimal, or None when ``value`` is None.
    Raises:
        ValidationError: If the value is a bool, not numeric, or not finite.
    """
    if value is None or isinstance(value, Decimal):
        number = value
    elif isinstance(value, bool):
        raise ValidationError("price must be a number")
    else:
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValidationError(f"price must be a number, got '{value}'") from exc
    if number is not None and not number.is_finite():
        raise ValidationError("price must be a finite number")
    return number


def format_price(value: Any) -> str:
    """Serialize a price for a request body without exponent notation.

    Args:
        value: Decimal, int, float or numeric string.
    Returns:
        A plain decimal string (``Decimal("1E+2")`` -> ``"100"``, ``0.1`` -> ``"0.1"``).
    Raises:
        ValidationError: If the value is not a finite number.
    """
    if isinstance(value, bool):
        raise ValidationError("price must be a finite number")
    number = value if isinstance(value, Decimal) else _to_decimal_or_none(str(value))
    if number is None or not number.is_finite():
        raise ValidationError("price must be a finite number")
    return format(number, "f")


def parse_date(value: Any) -> date | None:
    """Parse a server date in any of the known layouts.

    Args:
        value: A date string (YYYY/MM/DD, YYYY-MM-DD, MM/DD/YYYY, dd/MM/yyyy,
            optionally followed by HH:MM:SS), a datetime/date, or None.
    Returns:
        The date, or None when the value is empty or matches no known layout.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def to_number(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to a number (float, or int when it has no fractional part).

    Args:
        value: The value to convert; thousands separators are accepted.
        default: Default value if conversion fails.

    Returns:
        The converted number, or default if conversion fails or is not finite.
    """
    if value is None or isinstance(value, bool):
        return default
    number = _to_decimal_or_none(value)
    if number is None:
        return default
    as_float = float(number)
    # Convert to int if decimal part is .0
    return int(as_float) if as_float == int(as_float) else as_float


def to_price(value: Any) -> int | float | OrderType | str:
    """Parse a price: a number when numeric, else the order-type marker the server sent.

    ATO/ATC/MP/MTL/MOK/MAK orders carry a word instead of a price, so the result is
    an ``OrderType`` for a known marker and the raw string for anything else.
    """
    if value is None:
        return 0
    if isinstance(value, str) and not value.strip():
        return 0
    number = _to_decimal_or_none(value)
    if number is not None:
        as_float = float(number)
        return int(as_float) if as_float == int(as_float) else as_float
    text = str(value).strip()
    return OrderType.from_value(text) or text
