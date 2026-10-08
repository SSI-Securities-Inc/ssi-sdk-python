"""Pure policy for WebSocket reconnection (no I/O, shared by the sync and async clients)."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from ssi_sdk.constant import (
    WS_RATE_LIMIT_BACKOFF,
    WS_RECONNECT_MAX_DELAY,
    WS_TOKEN_REFRESH_LEAD,
)
from ssi_sdk.enums import StreamingMethod


@dataclass(frozen=True)
class ConnectionEvent:
    """A change in the state of a streaming connection (see ``on_connection``).

    ``state`` is one of ``"connected"`` (first connect), ``"reconnected"`` (re-opened after a
    drop, subscriptions restored), ``"disconnected"`` (the socket dropped; a reconnect follows
    when ``auto_reconnect`` is on) and ``"failed"`` (unrecoverable, e.g. a new OTP is needed;
    ``error`` says why and no reconnect will happen).
    """

    state: str
    reconnect_count: int = 0
    error: Exception | None = None


class RejectionKind(enum.Enum):
    """Why the server refused a connection it had already accepted."""

    AUTH = "auth"  # 401/403: the token is not (or no longer) valid
    RATE_LIMITED = "rate_limited"  # 429: more than 10 sockets for this client
    TRANSIENT = "transient"  # 5xx and anything else: try again later


def backoff_delay(
    attempt: int,
    base: float,
    cap: float = WS_RECONNECT_MAX_DELAY,
    jitter: float = 0.5,
) -> float:
    """Exponential backoff with jitter, bounded by ``cap`` so a loop can never run hot.

    Args:
        attempt: 0 for the first retry.
        base: Delay of the first retry in seconds.
        cap: Upper bound of the delay before jitter.
        jitter: A uniform random number in [0, 1); the delay is scaled into
            ``[50%, 100%]`` of the exponential value so many clients do not retry in step.
    Returns:
        Seconds to wait; always at least a small positive floor.
    """
    exponential = min(cap, max(base, 0.0) * (2 ** max(attempt, 0)))
    return max(0.05, exponential * (0.5 + 0.5 * min(max(jitter, 0.0), 1.0)))


def classify_rejection(message: dict[str, Any]) -> tuple[RejectionKind, float | None]:
    """Classify a ``{"code", "msg"}`` frame sent when the server refuses a connection.

    Returns:
        ``(kind, retry_after_seconds)``; ``retry_after`` is only set when the frame says so.
    """
    try:
        code = int(str(message.get("code")).strip())
    except (TypeError, ValueError):
        code = 0
    retry_after = None
    for key in ("retryAfter", "retry_after"):
        try:
            value = float(message[key])
        except (KeyError, TypeError, ValueError):
            continue
        if value >= 0:
            retry_after = value
            break
    if code in (401, 403):
        return RejectionKind.AUTH, retry_after
    if code == 429:
        return RejectionKind.RATE_LIMITED, retry_after
    return RejectionKind.TRANSIENT, retry_after


def rate_limit_wait(retry_after: float | None) -> float:
    """Wait after a 429: the server's ``Retry-After`` if longer, never under the floor."""
    return max(WS_RATE_LIMIT_BACKOFF, retry_after or 0.0)


def seconds_until_refresh(
    expires_at: float | int | None, now: float, lead: float = WS_TOKEN_REFRESH_LEAD
) -> float | None:
    """Seconds until the socket should be re-opened with a fresh token.

    The server only checks the JWT when a socket connects and never closes one whose token
    expires, so the client has to cycle the connection itself.

    Args:
        expires_at: Epoch seconds when the credentials stop working (the earlier of the
            access and refresh token); ``0``/None means unknown.
        now: Current epoch seconds.
        lead: How far ahead of the expiry to reconnect.
    Returns:
        Seconds to wait (>= 0), or None when no expiry is known (never refresh proactively).
    """
    if not expires_at or expires_at <= 0:
        return None
    return max(0.0, float(expires_at) - lead - now)


class SubscriptionBook:
    """Remembers what was subscribed so it can be re-sent after a reconnect."""

    def __init__(self) -> None:
        """Start with nothing subscribed."""
        self._topics: dict[str, dict[str, None]] = {}  # channel -> ordered set of topics

    def record(self, request: dict[str, Any]) -> None:
        """Apply an outgoing subscribe/unsubscribe request to the book (others are ignored)."""
        method = str(request.get("method", "")).lower()
        channel = request.get("channel")
        topics = request.get("topics")
        if not isinstance(channel, str) or not isinstance(topics, list):
            return
        if method == StreamingMethod.SUBSCRIBE.value:
            book = self._topics.setdefault(channel, {})
            for topic in topics:
                book[topic] = None
        elif method == StreamingMethod.UNSUBSCRIBE.value:
            book = self._topics.get(channel, {})
            for topic in topics:
                book.pop(topic, None)
            if not book:
                self._topics.pop(channel, None)

    def requests(self) -> list[dict[str, Any]]:
        """One subscribe request per channel that has topics, ready to send again."""
        return [
            {
                "method": StreamingMethod.SUBSCRIBE.value,
                "channel": channel,
                "topics": list(topics),
            }
            for channel, topics in self._topics.items()
            if topics
        ]

    def clear(self) -> None:
        """Forget everything (the caller is done with the connection)."""
        self._topics.clear()
