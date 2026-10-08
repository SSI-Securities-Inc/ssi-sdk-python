"""Streaming topic builder: validates every topic against what the server accepts."""

from __future__ import annotations

import re
from typing import Literal

from ssi_sdk.enums import Timeframe
from ssi_sdk.exceptions import ValidationError

# Topic types the server implements. ``asset.*``/``margin.*`` are not live yet, so they are
# deliberately absent: subscribing to them would only ever be silently ignored.
TOPIC_TYPES = frozenset(
    {
        "trade",
        "quote",
        "room",
        "put",
        "oddlot",
        "market",
        "order",
        "portfolio",
        "trade.index",
        "indexsummary",
    }
)

# Candle intervals the stream serves (and only on trade / trade.index).
STREAM_INTERVALS = frozenset({"tick", "1m", "5m"})
StreamInterval = Literal["tick", "1m", "5m"]  # for IDE completion on ``interval=``
_INTERVAL_TOPIC_TYPES = frozenset({"trade", "trade.index"})
_ACCOUNT_TOPIC_TYPES = frozenset({"order", "portfolio"})  # account numbers: sent as given

# The index of HNX+UPCOM is called HNXUPCOMINDEX on the server; UPCOMINDEX is the common alias.
_ALIASES = {"UPCOMINDEX": "HNXUPCOMINDEX"}

_ITEM = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?"  # a code, or a range A-B
_FILTER_RE = re.compile(rf"\*|{_ITEM}(?:,{_ITEM})*")


def _interval_text(interval: Timeframe | str | None) -> str | None:
    """Interval as the text that goes after ``@`` (``tick`` is case-insensitive, ``1M`` is not)."""
    if interval is None:
        return None
    text = str(getattr(interval, "value", interval))
    return "tick" if text.lower() == "tick" else text


def build_topic(
    topic_type: str, filter_: str = "*", interval: Timeframe | str | None = None
) -> str:
    """Build one topic string, e.g. ``trade.VNM@1m`` or ``trade.index.VN30``.

    Args:
        topic_type: One of :data:`TOPIC_TYPES`.
        filter_: ``*``, a code (``VNM``, ``HOSE``), a comma list (``VNM,FPT``) or a range
            (``A-B``). Codes are upper-cased (``vn30`` -> ``VN30``) except for ``order`` /
            ``portfolio`` accounts. ``UPCOMINDEX`` is rewritten to ``HNXUPCOMINDEX``.
        interval: ``tick``, ``1m`` or ``5m``; only valid for ``trade`` and ``trade.index``,
            and for ``trade.index`` only with a concrete code (not ``*``, a list or a range).
    Returns:
        The topic string.
    Raises:
        ValidationError: If the type, filter or interval is not accepted.
    """
    if topic_type not in TOPIC_TYPES:
        raise ValidationError(f"unknown topic type '{topic_type}'")
    if not isinstance(filter_, str) or not _FILTER_RE.fullmatch(filter_):
        raise ValidationError(f"invalid topic filter '{filter_}'")
    if topic_type not in _ACCOUNT_TOPIC_TYPES:
        filter_ = filter_.upper()  # the server upper-cases codes; ``vn30`` and ``VN30`` agree
    filter_ = ",".join(_ALIASES.get(item, item) for item in filter_.split(","))

    topic = f"{topic_type}.{filter_}"
    text = _interval_text(interval)
    if text is None:
        return topic
    if topic_type not in _INTERVAL_TOPIC_TYPES:
        raise ValidationError(f"interval is only valid for trade and trade.index, not {topic_type}")
    if text not in STREAM_INTERVALS:
        allowed = ", ".join(sorted(STREAM_INTERVALS))
        raise ValidationError(f"interval must be one of {allowed}, got '{text}'")
    if topic_type == "trade.index" and not re.fullmatch(r"[A-Za-z0-9]+", filter_):
        raise ValidationError("trade.index intervals need one concrete index, not a wildcard")
    return f"{topic}@{text}"


def build_topics(
    topic_type: str, filters: list[str], interval: Timeframe | str | None = None
) -> list[str]:
    """Build one topic per filter (see :func:`build_topic`); an empty list is an error."""
    if not filters:
        raise ValidationError("at least one symbol is required")
    return [build_topic(topic_type, item, interval) for item in filters]
