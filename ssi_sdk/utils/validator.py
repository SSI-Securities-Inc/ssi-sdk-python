"""Input validation utilities."""

from __future__ import annotations

from ssi_sdk.exceptions import ValidationError


def require_non_empty(value: str | None, field_name: str) -> str:
    """Validate that a string is not None or empty.

    Args:
        value: The value to check.
        field_name: Name of the field (for error messages).

    Returns:
        The validated non-empty string.

    Raises:
        ValidationError: If value is None or empty.
    """
    if not value:
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


def require_positive(value: int | float, field_name: str) -> int | float:
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


def require_non_negative(value: int | float, field_name: str) -> int | float:
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
