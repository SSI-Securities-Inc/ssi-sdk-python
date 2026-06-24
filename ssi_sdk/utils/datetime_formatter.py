"""Datetime formatter utilities."""

from datetime import datetime


def convert_to_datetime_str(date: datetime) -> str:
    """Format a datetime object as a 'YYYY/MM/DD HH:MM:SS' string.

    Args:
        date: The datetime object to format.
    Returns:
        The formatted date string in 'YYYY/MM/DD HH:MM:SS' format.
    """
    return date.strftime("%Y/%m/%d %H:%M:%S")


def convert_to_datetime(date_str: str) -> datetime:
    """Parse a 'YYYY/MM/DD HH:MM:SS' string into a datetime object.

    Args:
        date_str: The date string in 'YYYY/MM/DD HH:MM:SS' format.
    Returns:
        The parsed datetime object.
    Raises:
        ValueError: If date_str does not match the 'YYYY/MM/DD HH:MM:SS' format.
    """
    return datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S")


def today_date_str() -> str:
    """Get today's date as a 'YYYY/MM/DD' string.

    Returns:
        Today's date in 'YYYY/MM/DD' format.
    """
    return datetime.today().strftime("%Y/%m/%d")


def from_beginning_of_day() -> str:
    """Get the start of the current day as a 'YYYY/MM/DD 00:00:00' string.

    Returns:
        Today's date at midnight in 'YYYY/MM/DD HH:MM:SS' format.
    """
    return datetime.today().strftime("%Y/%m/%d 00:00:00")


def from_end_of_day() -> str:
    """Get the end of the current day as a 'YYYY/MM/DD 23:59:59' string.

    Returns:
        Today's date at the last second in 'YYYY/MM/DD HH:MM:SS' format.
    """
    return datetime.today().strftime("%Y/%m/%d 23:59:59")
