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
    """Token-bucket rate limiter (thread-safe)."""

    def __init__(self, max_per_second: int):
        self._max = max_per_second
        self._tokens = float(max_per_second)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request token is available."""
        if self._max <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._max, self._tokens + elapsed * self._max)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1.0 - self._tokens
                wait_seconds = deficit / self._max
            time.sleep(wait_seconds)

    async def async_acquire(self) -> None:
        """Async version of acquire."""
        if self._max <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._max, self._tokens + elapsed * self._max)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1.0 - self._tokens
                wait_seconds = deficit / self._max
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
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except httpx.TimeoutException as e:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(delay * (2**attempt))
            last_exc = e
    raise last_exc  # type: ignore[misc]


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
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except httpx.TimeoutException as e:
            if attempt >= max_retries:
                raise
            time.sleep(delay * (2**attempt))
            last_exc = e
    raise last_exc  # type: ignore[misc]
