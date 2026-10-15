"""Timeframe enum for SSI."""

from enum import Enum


class Timeframe(Enum):
    """Candle timeframe.

    The OHLC endpoint accepts 1d, 1m, 3m, 5m, 15m and 1h (``ALLOWED_TIMEFRAMES``); the stream
    serves only tick, 1m and 5m.

    Members:
        ``MINUTE_1``: ``"1m"``.
        ``MINUTE_3``: ``"3m"`` REST only.
        ``MINUTE_5``: ``"5m"``.
        ``MINUTE_15``: ``"15m"`` REST only.
        ``HOUR_1``: ``"1h"`` REST only.
        ``DAY_1``: ``"1d"`` REST only.
        ``WEEK_1``: ``"1w"`` not supported by the server (error 400210).
        ``MONTH_1``: ``"1M"`` not supported by the server (error 400210).
    """

    MINUTE_1 = "1m"
    MINUTE_3 = "3m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1M"


# Timeframes the OHLC endpoint accepts. ``1w``/``1M`` exist as members for backward
# compatibility, but the server rejects them with error 400210.
ALLOWED_TIMEFRAMES = frozenset(
    {
        Timeframe.DAY_1,
        Timeframe.MINUTE_1,
        Timeframe.MINUTE_3,
        Timeframe.MINUTE_5,
        Timeframe.MINUTE_15,
        Timeframe.HOUR_1,
    }
)
