"""Base Enum for SSI."""

from enum import Enum


class BaseEnum(Enum):
    """Base Enum class with helper methods."""

    @classmethod
    def from_value(cls, value):
        """Safely convert a value to the enum member."""
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            pass
        if isinstance(value, str):
            val_upper = value.upper()
            for member in cls:
                if member.name == val_upper or str(member.value).upper() == val_upper:
                    return member
        return None
