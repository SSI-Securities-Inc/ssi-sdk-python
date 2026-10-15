"""Pure helpers for decoding and routing WebSocket frames (no I/O, shared by sync and async)."""

from __future__ import annotations

import json
import logging
from typing import Any

from ssi_sdk.constant import (
    WS_KEY_CHANNEL,
    WS_MAX_FRAME_BYTES,
    WS_ROUTE_ACK,
    WS_ROUTE_ERROR,
    WS_ROUTE_ID,
    WS_ROUTE_LIST_SUBSCRIPTION,
)

logger = logging.getLogger("ssi_sdk.transport.dispatch")


def decode_message(raw: Any) -> dict[str, Any] | None:
    """Decode a raw frame into a dict.

    Args:
        raw: Text/bytes frame as received.
    Returns:
        The decoded dict, or None when the frame is not JSON or not a JSON object. The frame
        content is never logged (it can carry account numbers); only its size is.
    """
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Received non-JSON message (%d bytes)", len(raw or ""))
        return None
    if not isinstance(message, dict):
        logger.warning("Received non-object message (%s)", type(message).__name__)
        return None
    return message


def is_ack(message: dict[str, Any]) -> bool:
    """Whether a frame is a reply to a request (has ``method`` and ``status``, no ``topic``)."""
    return "method" in message and "status" in message and "topic" not in message


def routes_of(message: dict[str, Any]) -> list[str]:
    """Return every route whose handlers should see this frame, most specific first.

    * a frame with a ``channel`` goes to that channel's handlers (``DATA``/``TRADING``/
      ``HEARTBEAT``), and an ack among them also goes to the ack route;
    * ``{"code", "msg"}`` without a channel is the server rejecting the connection;
    * a frame with an ``id`` answers a request sent on the trading socket;
    * ``{"trading": "...", "data": "..."}`` is the reply to ``LIST_SUBSCRIPTION``.

    Anything else yields no route and is dropped.
    """
    routes: list[str] = []
    channel = message.get(WS_KEY_CHANNEL)
    if isinstance(channel, str) and channel:
        routes.append(channel)
        if is_ack(message):
            routes.append(WS_ROUTE_ACK)
        return routes
    if "id" in message:
        routes.append(WS_ROUTE_ID)
    elif "code" in message and ("msg" in message or "message" in message):
        routes.append(WS_ROUTE_ERROR)
    elif "topic" not in message and ("trading" in message or "data" in message):
        routes.append(WS_ROUTE_LIST_SUBSCRIPTION)
    elif is_ack(message):
        routes.append(WS_ROUTE_ACK)
    return routes


def ack_error_category(message: dict[str, Any]) -> str | None:
    """Why the server refused a request, from an ``{"status": "error"}`` ack.

    Returns:
        ``"Denied (account)"``, ``"Denied (scope)"``, ``"Invalid"`` or ``"error"``; ``None`` when
        the frame is not an error ack. Only the category is returned: the server's text names the
        topics (and so possibly account numbers), which must not reach a log.
    """
    if not is_ack(message) or str(message.get("status", "")).lower() != "error":
        return None
    text = str(message.get("message") or "")
    for category in ("Denied (account)", "Denied (scope)", "Invalid"):
        if category.lower() in text.lower():
            return category
    return "error"


def split_request(
    data: dict[str, Any], max_bytes: int = WS_MAX_FRAME_BYTES
) -> list[dict[str, Any]]:
    """Split a subscribe/unsubscribe request whose JSON would exceed ``max_bytes``.

    The server drops frames over its ``MaxMessageSize`` (4096 bytes), so a request naming many
    topics is sent as several requests with the same ``method``/``channel`` and a share of the
    topics each. Anything else (no ``topics`` list, or small enough) is returned unchanged.
    """
    topics = data.get("topics")
    if not isinstance(topics, list) or len(json.dumps(data).encode("utf-8")) <= max_bytes:
        return [data]
    parts: list[dict[str, Any]] = []
    current: list[Any] = []
    for topic in topics:
        trial = {**data, "topics": current + [topic]}
        if current and len(json.dumps(trial).encode("utf-8")) > max_bytes:
            parts.append({**data, "topics": current})
            current = []
        current.append(topic)
    if current:
        parts.append({**data, "topics": current})
    return parts


def split_subscriptions(message: dict[str, Any]) -> dict[str, list[str]]:
    """Parse a ``LIST_SUBSCRIPTION`` reply into ``{"trading": [...], "data": [...]}``.

    The server joins topics with ``;``. A missing key or an empty string is an empty list.
    """
    result: dict[str, list[str]] = {}
    for key in ("trading", "data"):
        value = message.get(key)
        text = value if isinstance(value, str) else ""
        result[key] = [topic for topic in text.split(";") if topic]
    return result
