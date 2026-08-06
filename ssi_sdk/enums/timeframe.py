"""Timeframe enum for SSI."""

from enum import Enum


class Timeframe(Enum):
    """Enum representing different timeframes for SSI."""

    MINUTE_1 = "1m"
    MINUTE_3 = "3m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1M"
