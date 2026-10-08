"""Retry and rate-limiting utilities."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from ssi_sdk.constant import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
)


class RateLimiter:
    """Token-bucket rate limiter (thread-safe) that follows what the server says.

    ``max_per_second`` is the caller's own ceiling (0 = unlimited). :meth:`cap` lowers the
    effective rate to the server's advertised limit, and :meth:`pause` holds every caller for
    a while (the server asked us to wait). A rate of 0 stays unlimited: the caller opted out.
    """

    def __init__(self, max_per_second: int):
        self._configured = max_per_second
        self._max = max_per_second
        self._tokens = float(max_per_second)
        self._last = time.monotonic()
        self._pause_until = 0.0
        self._lock = threading.Lock()

    @property
    def rate(self) -> int:
        """The effective requests-per-second ceiling now (0 = unlimited)."""
        return self._max

    def cap(self, server_limit: int | None) -> None:
        """Never go faster than ``server_limit`` per second (ignored when unlimited/invalid)."""
        if not server_limit or server_limit <= 0 or self._configured <= 0:
            return
        with self._lock:
            self._max = min(self._configured, server_limit)
            self._tokens = min(self._tokens, float(self._max))

    def pause(self, seconds: float) -> None:
        """Make every :meth:`acquire` wait until ``seconds`` from now (never shortens a pause)."""
        if seconds <= 0:
            return
        with self._lock:
            self._pause_until = max(self._pause_until, time.monotonic() + seconds)

    def _reserve(self) -> float:
        """Take a token and return 0, or return how long to wait before trying again."""
        with self._lock:
            now = time.monotonic()
            if now < self._pause_until:
                return self._pause_until - now
            if self._max <= 0:
                return 0.0
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._max, self._tokens + elapsed * self._max)
            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0
            return (1.0 - self._tokens) / self._max

    def acquire(self) -> None:
        """Block until a request token is available."""
        while (wait_seconds := self._reserve()) > 0:
            time.sleep(wait_seconds)

    async def async_acquire(self) -> None:
        """Async version of acquire."""
        while (wait_seconds := self._reserve()) > 0:
            await asyncio.sleep(wait_seconds)


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    delay: float = DEFAULT_RETRY_DELAY,
    **kwargs: Any,
) -> Any:
    """Retry an async function on timeout with exponential backoff.

    Only retries on ``httpx.TimeoutException``. All other exceptions are
    raised immediately without retrying.
    """
    max_retries = max(0, max_retries)
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except httpx.TimeoutException:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(delay * (2**attempt))
    raise AssertionError("unreachable")  # pragma: no cover


def retry_sync(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    delay: float = DEFAULT_RETRY_DELAY,
    **kwargs: Any,
) -> Any:
    """Retry a synchronous function on timeout with exponential backoff.

    Only retries on ``httpx.TimeoutException``. All other exceptions are
    raised immediately without retrying.
    """
    max_retries = max(0, max_retries)
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except httpx.TimeoutException:
            if attempt >= max_retries:
                raise
            time.sleep(delay * (2**attempt))
    raise AssertionError("unreachable")  # pragma: no cover
