"""WebSocket client for SSI Streaming."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import re
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import websocket as ws_sync
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_async_connect

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    AUTH_SCHEME_BEARER,
    CONTENT_TYPE_JSON,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    HEADER_CONTENT_TYPE,
    WS_ROUTE_ERROR,
    WS_THREAD_JOIN_TIMEOUT,
    WS_THREAD_NAME,
)
from ssi_sdk.exceptions import AuthenticationError, WebSocketError
from ssi_sdk.transport.dispatch import (
    ack_error_category,
    decode_message,
    routes_of,
    split_request,
)
from ssi_sdk.transport.reconnect import (
    ConnectionEvent,
    RejectionKind,
    SubscriptionBook,
    backoff_delay,
    classify_rejection,
    rate_limit_wait,
    seconds_until_refresh,
)
from ssi_sdk.utils.redact import mask_bearer, safe_url

logger = logging.getLogger("ssi_sdk.transport.websocket")

MessageHandler = Callable[[dict[str, Any]], Any]
TokenProvider = Callable[[bool], "str | None | Awaitable[str | None]"]

# A connection that lasted at least this long counts as healthy: the backoff starts over.
_STABLE_SECONDS = 10.0


def _handshake_status(error: BaseException) -> int | None:
    """HTTP status of a failed WebSocket handshake, across websockets versions."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None) or getattr(error, "status_code", None)
    if status is None:
        match = re.search(r"HTTP (\d{3})|status (\d{3})", str(error))
        if match:
            status = int(match.group(1) or match.group(2))
    return int(status) if status is not None else None


def _log_handler_error(route: str, error: Exception) -> None:
    """Log a failing user handler without echoing its message unmasked; traceback at DEBUG."""
    logger.error(
        "Error in handler for route '%s': %s: %s",
        route,
        type(error).__name__,
        mask_bearer(str(error)),
    )
    logger.debug("Handler traceback", exc_info=True)


def _log_ack_error(message: dict[str, Any]) -> None:
    """Warn when the server refuses a subscribe/unsubscribe (e.g. ``order.*`` on an account the
    token does not own), so the refusal is not silent. Only the category is logged."""
    category = ack_error_category(message)
    if category is not None:
        logger.warning(
            "Server refused a %s request on %s: %s",
            message.get("method") or "?",
            message.get("channel") or "?",
            category,
        )


def _require_wss(url: str) -> None:
    """Refuse to open a socket that is not TLS-protected: the bearer token travels in it."""
    if urlparse(url).scheme.lower() != "wss":
        raise WebSocketError(f"streaming_url must use wss://, got {safe_url(url)!r}")


def _auth_error(status: int) -> AuthenticationError:
    """Error for credentials the server keeps rejecting even after a token refresh."""
    return AuthenticationError(
        f"WebSocket authentication failed after refreshing the token ({status})",
        code=str(status),
        status_code=status,
    )


class AsyncWebSocketClient:
    """Async WebSocket client for SSI real-time streaming.

    ``connect()`` starts a supervisor task that keeps one socket open: it re-opens the socket
    after a drop (exponential backoff with jitter, capped), always with a fresh token from
    ``token_provider``, re-opens it ahead of the token's expiry (the server never closes a
    socket whose JWT expired, it only checks at connect), and re-sends every subscription.
    The old socket is always closed before a new one opens: the server allows only 10 per
    client and a leak would exhaust that quota.
    """

    def __init__(
        self,
        config: Config,
        *,
        token_provider: TokenProvider | None = None,
        expiry_provider: Callable[[], float | int] | None = None,
        auto_reconnect: bool | None = None,
        connect_fn: Callable[..., Awaitable[Any]] | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        random_fn: Callable[[], float] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        """Initialize the async WebSocket client.

        Args:
            config: SDK configuration (``streaming_url``, ``proxy``, ``max_retries`` ...).
            token_provider: ``provider(force_refresh) -> token`` (sync or async), called before
                every connect. ``force_refresh`` is True after the server rejected the token
                and when cycling for expiry. Without it the token from ``set_token`` is used.
            expiry_provider: Returns the epoch second when the credentials stop working (the
                earlier of access and refresh token); 0 means unknown.
            auto_reconnect: Re-open the socket after a drop. Defaults to
                ``config.auto_reconnect``.
            connect_fn: Coroutine factory used to open a socket (tests inject a fake).
            sleep_fn: Awaitable sleep (tests inject a fake clock).
            random_fn: Uniform random in [0, 1) used for jitter.
            clock: Wall clock in epoch seconds.
        """
        self._config = config
        self._connection: ClientConnection | None = None
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._supervisor: asyncio.Task[None] | None = None
        self._token: str | None = None
        self._token_provider = token_provider
        self._expiry_provider = expiry_provider
        self._auto_reconnect = config.auto_reconnect if auto_reconnect is None else auto_reconnect
        self._connect_fn = connect_fn or ws_async_connect
        self._sleep = sleep_fn or asyncio.sleep
        self._random = random_fn or random.random
        self._clock = clock or time.time
        self._closing = False
        self._subscriptions = SubscriptionBook()
        self._rejection: dict[str, Any] | None = None
        self._rejected = asyncio.Event()
        self._last_error: Exception | None = None
        self._reconnect_count = 0
        self.on_state: Callable[[ConnectionEvent], Any] | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }

    def set_token(self, token: str) -> None:
        """Set a static authentication token (used when no ``token_provider`` is given).

        Args:
            token: The bearer token used to authenticate the connection.
        """
        self._token = token

    @property
    def last_error(self) -> Exception | None:
        """The error that ended the supervisor (a connection that could not be recovered)."""
        return self._last_error

    @property
    def reconnect_count(self) -> int:
        """How many times the socket was re-opened after the first connect."""
        return self._reconnect_count

    def _emit(self, state: str, error: Exception | None = None) -> None:
        """Tell ``on_state`` (if set) about a connection change; its errors never propagate."""
        handler = self.on_state
        if handler is None:
            return
        try:
            result = handler(ConnectionEvent(state, self._reconnect_count, error))
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error in the on_state handler")

    async def connect(self) -> None:
        """Open the WebSocket and keep it open.

        Returns once the first connection is established; later drops are handled in the
        background (see the class docstring).

        Raises:
            WebSocketError: If ``streaming_url`` is not ``wss://``, or the first connection
                fails after ``config.max_retries`` attempts.
            AuthenticationError: If the server keeps rejecting the credentials, or they cannot
                be renewed without a new OTP (``ReauthenticationRequired``).
        """
        if self._supervisor is not None and not self._supervisor.done():
            return
        _require_wss(self._config.streaming_url)
        self._closing = False
        self._last_error = None
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._supervisor = asyncio.create_task(self._supervise(ready))
        try:
            await ready
        except BaseException:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """Stop the supervisor, close the socket and forget the subscriptions."""
        self._closing = True
        task, self._supervisor = self._supervisor, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-exception-caught
                pass
        await self._close_connection()
        self._subscriptions.clear()
        logger.info("WebSocket disconnected")

    def on(self, channel: str, handler: MessageHandler | None) -> None:
        """Register a handler for a specific channel/message type.

        Passing ``None`` clears all handlers for the channel (equivalent to
        calling ``off(channel)``).

        Args:
            channel: The channel name to subscribe to.
            handler: Callback function invoked with the message data, or
                ``None`` to clear the channel's handlers.
        """
        if handler is None:
            self._handlers.pop(channel, None)
            return
        self._handlers[channel] = [handler]

    def off(self, channel: str, handler: MessageHandler | None = None) -> None:
        """Unregister handler(s) for a channel.

        Args:
            channel: The channel name.
            handler: Specific handler to remove, or None to remove all.
        """
        if channel not in self._handlers:
            return
        if handler is None:
            del self._handlers[channel]
        else:
            self._handlers[channel] = [h for h in self._handlers[channel] if h is not handler]

    async def send(self, data: dict[str, Any]) -> None:
        """Send a message through the WebSocket.

        A successful subscribe/unsubscribe is remembered so it is re-sent after a reconnect.

        Args:
            data: The message payload to serialize as JSON and send.
        Raises:
            WebSocketError: If not connected or if sending the message fails.
        """
        connection = self._connection
        if not connection:
            raise WebSocketError("Not connected. Call connect() first.")
        try:
            for part in split_request(data):
                await connection.send(json.dumps(part))
        except Exception as e:
            raise WebSocketError(f"Failed to send message: {e}") from e
        self._subscriptions.record(data)

    # ── supervisor ───────────────────────────────────────────

    async def _current_token(self, force_refresh: bool) -> str | None:
        """Get the token for the next connect (never logged)."""
        if self._token_provider is None:
            return self._token
        result = self._token_provider(force_refresh)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _open(self, force_refresh: bool) -> Any:
        """Open one socket with a freshly obtained token."""
        token = await self._current_token(force_refresh)
        headers = dict(self._headers)
        if token:
            headers[HEADER_AUTHORIZATION] = f"{AUTH_SCHEME_BEARER}{token}"
        kwargs: dict[str, Any] = {"additional_headers": headers}
        if self._config.proxy:
            kwargs["proxy"] = self._config.proxy
        url = self._config.streaming_url
        logger.debug("Connecting to WebSocket %s", safe_url(url))
        connection = await self._connect_fn(url, **kwargs)
        self._connection = connection
        self._rejection = None
        self._rejected.clear()
        logger.info("WebSocket connected to %s", safe_url(url))
        return connection

    async def _close_connection(self) -> None:
        """Close the current socket, if any. Always called before another one is opened."""
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                await connection.close()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.debug("Error while closing the WebSocket", exc_info=True)

    async def _resubscribe(self, connection: Any) -> None:
        """Re-send every remembered subscription on a new socket."""
        for request in self._subscriptions.requests():
            for part in split_request(request):
                await connection.send(json.dumps(part))

    async def _serve(self, connection: Any) -> str:
        """Run one socket until it closes, the server rejects it, or it must be cycled.

        Returns:
            ``"closed"``, ``"rejected"`` or ``"refresh"``.
        """
        listen = asyncio.create_task(self._listen(connection))
        rejected = asyncio.create_task(self._rejected.wait())
        waiting: dict[asyncio.Task, str] = {listen: "closed", rejected: "rejected"}
        delay = seconds_until_refresh(
            self._expiry_provider() if self._expiry_provider else 0, self._clock()
        )
        if delay is not None:
            waiting[asyncio.create_task(self._sleep(delay))] = "refresh"
        try:
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            reason = next(waiting[task] for task in waiting if task in done)
            # A refusal frame is followed by a close; report the cause, not the symptom.
            return "rejected" if reason == "closed" and self._rejection else reason
        finally:
            for task in waiting:
                task.cancel()
            await asyncio.gather(*waiting, return_exceptions=True)

    def _fail(self, error: Exception, ready: asyncio.Future[None] | None) -> None:
        """Record a fatal error and, if the first connect is still pending, raise it there."""
        self._last_error = error
        logger.error("WebSocket stopped: %s", type(error).__name__)
        self._emit("failed", error)
        if ready is not None and not ready.done():
            ready.set_exception(error)

    async def _supervise(self, ready: asyncio.Future[None]) -> None:
        """Keep one socket open until ``disconnect()`` (see the class docstring)."""
        pending: asyncio.Future[None] | None = ready
        attempt = 0
        auth_retried = False
        force_refresh = False
        try:
            while not self._closing:
                try:
                    connection = await self._open(force_refresh)
                except asyncio.CancelledError:
                    raise
                except AuthenticationError as exc:
                    self._fail(exc, pending)  # cannot be fixed by retrying: needs a new OTP
                    return
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    status = _handshake_status(exc)
                    if status in (401, 403):
                        if auth_retried:
                            self._fail(_auth_error(status), pending)
                            return
                        auth_retried, force_refresh = True, True
                        continue
                    wait = rate_limit_wait(None) if status == 429 else self._backoff(attempt)
                    attempt += 1
                    if pending is not None and attempt >= max(1, self._config.max_retries):
                        self._fail(
                            WebSocketError(
                                f"Failed to connect to {safe_url(self._config.streaming_url)} "
                                f"after {attempt} attempts: {type(exc).__name__}"
                            ),
                            pending,
                        )
                        return
                    logger.warning(
                        "WebSocket connect attempt %d failed (%s); retrying in %.1fs",
                        attempt,
                        type(exc).__name__,
                        wait,
                    )
                    await self._sleep(wait)
                    continue

                opened_at = self._clock()
                force_refresh = False
                try:
                    await self._resubscribe(connection)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.warning("Could not restore subscriptions", exc_info=True)
                if pending is not None:
                    pending.set_result(None)
                    pending = None
                    self._emit("connected")
                else:
                    self._reconnect_count += 1
                    logger.info("WebSocket reconnected (#%d)", self._reconnect_count)
                    self._emit("reconnected")

                reason = await self._serve(connection)
                await self._close_connection()
                if self._closing:
                    return
                self._emit("disconnected")
                stable = self._clock() - opened_at > _STABLE_SECONDS
                attempt = 0 if stable else attempt + 1

                if reason == "refresh":
                    force_refresh = True  # the old token is about to expire: get a new one
                    continue
                if reason == "rejected":
                    kind, retry_after = classify_rejection(self._rejection or {})
                    if kind is RejectionKind.AUTH:
                        if auth_retried:
                            self._fail(_auth_error(401), None)
                            return
                        auth_retried, force_refresh = True, True
                        continue
                    wait = (
                        rate_limit_wait(retry_after)
                        if kind is RejectionKind.RATE_LIMITED
                        else self._backoff(attempt)
                    )
                else:
                    auth_retried = False
                    if not self._auto_reconnect:
                        return
                    wait = self._backoff(attempt)
                logger.info("WebSocket closed; reconnecting in %.1fs", wait)
                await self._sleep(wait)
        finally:
            await self._close_connection()
            if pending is not None and not pending.done():
                pending.cancel()

    def _backoff(self, attempt: int) -> float:
        """Delay before reconnect attempt number ``attempt`` (exponential, jittered, capped)."""
        return backoff_delay(attempt, float(self._config.retry_delay), jitter=self._random())

    # ── receive ──────────────────────────────────────────────

    async def _listen(self, connection: Any) -> None:
        """Receive frames from one socket and dispatch them until it closes."""
        try:
            async for raw_message in connection:
                message = decode_message(raw_message)
                if message is None:
                    continue
                if WS_ROUTE_ERROR in routes_of(message):
                    self._rejection = message
                    self._rejected.set()
                await self._dispatch(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("WebSocket listen error")

    async def _dispatch(self, message: dict[str, Any]) -> None:
        """Hand a decoded frame to every handler on its routes.

        A handler that raises is logged and skipped: it must not end the listen loop.
        """
        _log_ack_error(message)
        for route in routes_of(message):
            for handler in list(self._handlers.get(route, [])):
                try:
                    result = handler(message)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _log_handler_error(route, e)

    async def wait(self, timeout: float | None = None) -> None:
        """Block until the supervisor ends (disconnect or unrecoverable error) or timeout.

        Args:
            timeout: Maximum seconds to wait, or None to wait indefinitely.
        """
        task = self._supervisor
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    @property
    def is_connected(self) -> bool:
        """Whether a socket is currently open.

        Returns:
            True if the connection is open and the supervisor is running.
        """
        return (
            self._connection is not None
            and self._supervisor is not None
            and not self._supervisor.done()
        )


class WebSocketClient:
    """Synchronous WebSocket client for SSI real-time streaming.

    Uses ``websocket-client`` (sync). ``connect()`` starts a supervisor thread that keeps one
    socket open with the same policy as :class:`AsyncWebSocketClient`: reconnect with capped,
    jittered backoff and a fresh token (``token_provider`` is called from that background
    thread), cycle the socket ahead of token expiry, honour the server's refusal frames, and
    re-send every subscription. The old socket is always closed before a new one opens.
    """

    def __init__(
        self,
        config: Config,
        *,
        token_provider: Callable[[bool], str | None] | None = None,
        expiry_provider: Callable[[], float | int] | None = None,
        auto_reconnect: bool | None = None,
        app_factory: Callable[..., Any] | None = None,
        random_fn: Callable[[], float] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        """Initialize the sync WebSocket client.

        Args:
            config: SDK configuration (``streaming_url``, ``proxy``, ``timeout`` ...).
            token_provider: ``provider(force_refresh) -> token``, called before every connect.
                ``force_refresh`` is True after the server rejected the token and when cycling
                for expiry. Without it the token from ``set_token`` is used.
            expiry_provider: Returns the epoch second when the credentials stop working (the
                earlier of access and refresh token); 0 means unknown.
            auto_reconnect: Re-open the socket after a drop. Defaults to
                ``config.auto_reconnect``.
            app_factory: Builds the socket app (``WebSocketApp`` by default; tests inject one).
            random_fn: Uniform random in [0, 1) used for jitter.
            clock: Wall clock in epoch seconds.
        """
        self._config = config
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._token: str | None = None
        self._token_provider = token_provider
        self._expiry_provider = expiry_provider
        self._auto_reconnect = config.auto_reconnect if auto_reconnect is None else auto_reconnect
        self._app_factory = app_factory or ws_sync.WebSocketApp
        self._random = random_fn or random.random
        self._clock = clock or time.time
        self._ws: Any = None
        self._supervisor: threading.Thread | None = None
        self._closing = threading.Event()
        self._opened = threading.Event()
        self._open_seen = False
        self._ready = threading.Event()
        self._ready_error: Exception | None = None
        self._send_lock = threading.Lock()
        self._subscriptions = SubscriptionBook()
        self._rejection: dict[str, Any] | None = None
        self._handshake_status: int | None = None
        self._cycle = False
        self._first_connect = True
        self._last_error: Exception | None = None
        self._reconnect_count = 0
        self.on_state: Callable[[ConnectionEvent], Any] | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }

    def set_token(self, token: str) -> None:
        """Set a static authentication token (used when no ``token_provider`` is given).

        Args:
            token: The bearer token used to authenticate the connection.
        """
        self._token = token

    @property
    def last_error(self) -> Exception | None:
        """The error that ended the supervisor (a connection that could not be recovered)."""
        return self._last_error

    @property
    def reconnect_count(self) -> int:
        """How many times the socket was re-opened after the first connect."""
        return self._reconnect_count

    def _emit(self, state: str, error: Exception | None = None) -> None:
        """Tell ``on_state`` (if set) about a connection change; its errors never propagate.

        It runs on the SDK's own thread, so keep the handler short.
        """
        handler = self.on_state
        if handler is None:
            return
        try:
            handler(ConnectionEvent(state, self._reconnect_count, error))
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error in the on_state handler")

    def connect(self) -> None:
        """Open the WebSocket and keep it open.

        Returns once the first connection is established; later drops are handled by the
        background thread.

        Raises:
            WebSocketError: If the first connection fails after ``config.max_retries`` attempts
                or does not come up within ``config.timeout`` seconds.
            AuthenticationError: If the server keeps rejecting the credentials, or they cannot
                be renewed without a new OTP (``ReauthenticationRequired``).
        """
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        _require_wss(self._config.streaming_url)
        self._closing.clear()
        self._ready.clear()
        self._ready_error = None
        self._last_error = None
        self._supervisor = threading.Thread(
            target=self._supervise, daemon=True, name=WS_THREAD_NAME
        )
        self._supervisor.start()
        timeout = self._config.timeout or 30
        if not self._ready.wait(timeout=timeout):
            self.disconnect()
            url = safe_url(self._config.streaming_url)
            raise WebSocketError(f"Timed out waiting for WebSocket connection to {url}")
        if self._ready_error is not None:
            error, self._ready_error = self._ready_error, None
            self.disconnect()
            raise error

    def disconnect(self) -> None:
        """Stop the supervisor, close the socket and forget the subscriptions."""
        self._closing.set()
        self._opened.clear()
        app = self._ws
        if app is not None:
            try:
                app.close()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.debug("Error while closing the WebSocket", exc_info=True)
        thread = self._supervisor
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=WS_THREAD_JOIN_TIMEOUT)
        self._ws = None
        self._supervisor = None
        self._subscriptions.clear()
        logger.info("WebSocket disconnected")

    def on(self, channel: str, handler: MessageHandler | None) -> None:
        """Register a handler for a specific channel/message type.

        Passing ``None`` clears all handlers for the channel (equivalent to
        calling ``off(channel)``).

        Args:
            channel: The channel name to subscribe to.
            handler: Callback function invoked with the message data, or
                ``None`` to clear the channel's handlers.
        """
        if handler is None:
            self._handlers.pop(channel, None)
            return
        self._handlers[channel] = [handler]

    def off(self, channel: str, handler: MessageHandler | None = None) -> None:
        """Unregister handler(s) for a channel.

        Args:
            channel: The channel name.
            handler: Specific handler to remove, or None to remove all.
        """
        if channel not in self._handlers:
            return
        if handler is None:
            del self._handlers[channel]
        else:
            self._handlers[channel] = [h for h in self._handlers[channel] if h is not handler]

    def send(self, data: dict[str, Any]) -> None:
        """Send a message through the WebSocket (safe to call from any thread).

        A successful subscribe/unsubscribe is remembered so it is re-sent after a reconnect.

        Args:
            data: The message payload to serialize as JSON and send.
        Raises:
            WebSocketError: If not connected or if sending the message fails.
        """
        app = self._ws
        if not app or self._closing.is_set() or not self._opened.is_set():
            raise WebSocketError("Not connected. Call connect() first.")
        try:
            with self._send_lock:
                for part in split_request(data):
                    app.send(json.dumps(part))
        except Exception as e:
            raise WebSocketError(f"Failed to send message: {e}") from e
        self._subscriptions.record(data)

    # ── supervisor ───────────────────────────────────────────

    def _backoff(self, attempt: int) -> float:
        """Delay before reconnect attempt number ``attempt`` (exponential, jittered, capped)."""
        return backoff_delay(attempt, float(self._config.retry_delay), jitter=self._random())

    def _wait(self, seconds: float) -> None:
        """Sleep between connection attempts; ``disconnect()`` wakes it immediately."""
        self._closing.wait(seconds)

    def _fail(self, error: Exception, first: bool) -> None:
        """Record a fatal error and, if the first connect is still pending, raise it there."""
        self._last_error = error
        logger.error("WebSocket stopped: %s", type(error).__name__)
        self._emit("failed", error)
        if first:
            self._ready_error = error
            self._ready.set()

    def _run_forever_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``run_forever`` (proxy settings)."""
        kwargs: dict[str, Any] = {}
        if self._config.proxy:
            parsed = urlparse(self._config.proxy)
            kwargs["http_proxy_host"] = parsed.hostname
            kwargs["http_proxy_port"] = parsed.port
            if parsed.username:
                kwargs["http_proxy_auth"] = (parsed.username, parsed.password)
            if parsed.scheme.startswith("socks"):
                kwargs["proxy_type"] = parsed.scheme
        return kwargs

    def _supervise(self) -> None:
        """Keep one socket open until ``disconnect()`` (see the class docstring)."""
        first = True
        attempt = 0
        auth_retried = False
        force_refresh = False
        while not self._closing.is_set():
            # 1. a fresh token, obtained on this background thread
            try:
                token = (
                    self._token_provider(force_refresh)
                    if self._token_provider
                    else self._token
                )
            except AuthenticationError as exc:
                self._fail(exc, first)  # cannot be fixed by retrying: needs a new OTP
                return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                token = None
                token_error: Exception | None = exc
            else:
                token_error = None
            if self._closing.is_set():  # disconnect() while the token was being fetched
                return

            # 2. open one socket and serve it until it ends
            opened_at = self._clock()
            self._handshake_status = None
            self._rejection = None
            self._cycle = False
            self._open_seen = False
            self._opened.clear()
            if token_error is None:
                self._serve_once(token, first)
            was_open = self._open_seen  # the socket came up at least once, then ended
            self._opened.clear()
            app, self._ws = self._ws, None
            if app is not None:  # the old socket is fully closed before another opens
                try:
                    app.close()
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.debug("Error while closing the WebSocket", exc_info=True)
            if self._closing.is_set():
                return
            force_refresh = False

            # 3. decide what happens next
            if not was_open:
                status = self._handshake_status
                if status in (401, 403):
                    if auth_retried:
                        self._fail(_auth_error(status), first)
                        return
                    auth_retried, force_refresh = True, True
                    continue
                wait = rate_limit_wait(None) if status == 429 else self._backoff(attempt)
                attempt += 1
                if first and attempt >= max(1, self._config.max_retries):
                    cause = type(token_error).__name__ if token_error else "handshake failed"
                    self._fail(
                        WebSocketError(
                            f"Failed to connect to {safe_url(self._config.streaming_url)} "
                            f"after {attempt} attempts: {cause}"
                        ),
                        first,
                    )
                    return
                logger.warning(
                    "WebSocket connect attempt %d failed; retrying in %.1fs", attempt, wait
                )
                self._wait(wait)
                continue

            first = False
            self._emit("disconnected")
            stable = self._clock() - opened_at > _STABLE_SECONDS
            attempt = 0 if stable else attempt + 1
            if self._cycle:
                force_refresh = True  # the old token is about to expire: get a new one
                continue
            if self._rejection is not None:
                kind, retry_after = classify_rejection(self._rejection)
                if kind is RejectionKind.AUTH:
                    if auth_retried:
                        self._fail(_auth_error(401), False)
                        return
                    auth_retried, force_refresh = True, True
                    continue
                wait = (
                    rate_limit_wait(retry_after)
                    if kind is RejectionKind.RATE_LIMITED
                    else self._backoff(attempt)
                )
            else:
                auth_retried = False
                if not self._auto_reconnect:
                    return
                wait = self._backoff(attempt)
            logger.info("WebSocket closed; reconnecting in %.1fs", wait)
            self._wait(wait)

    def _serve_once(self, token: str | None, first: bool) -> None:
        """Open one socket and block until it closes."""
        headers = dict(self._headers)
        if token:
            headers[HEADER_AUTHORIZATION] = f"{AUTH_SCHEME_BEARER}{token}"
        url = self._config.streaming_url
        logger.debug("Connecting to WebSocket %s", safe_url(url))
        self._first_connect = first
        self._ws = self._app_factory(
            url,
            header=[f"{k}: {v}" for k, v in headers.items()],
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        timer = self._schedule_cycle()
        try:
            self._ws.run_forever(**self._run_forever_kwargs())
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("WebSocket run_forever ended with an error", exc_info=True)
        finally:
            if timer is not None:
                timer.cancel()

    def _schedule_cycle(self) -> threading.Timer | None:
        """Plan the proactive reconnect that replaces the token before it expires."""
        delay = seconds_until_refresh(
            self._expiry_provider() if self._expiry_provider else 0, self._clock()
        )
        if delay is None:
            return None

        def _cycle() -> None:
            self._cycle = True
            app = self._ws
            if app is not None:
                app.close()

        timer = threading.Timer(delay, _cycle)
        timer.daemon = True
        timer.start()
        return timer

    # ── callbacks (run on the socket's thread) ───────────────

    def _on_open(self, ws_app: Any) -> None:
        """Restore subscriptions, then signal that the socket is up."""
        for request in (part for r in self._subscriptions.requests() for part in split_request(r)):
            try:
                ws_app.send(json.dumps(request))
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("Could not restore subscriptions", exc_info=True)
                break
        self._open_seen = True
        self._opened.set()
        if self._first_connect:
            self._ready.set()
            self._emit("connected")
        else:
            self._reconnect_count += 1
            logger.info("WebSocket reconnected (#%d)", self._reconnect_count)
            self._emit("reconnected")
        logger.info("WebSocket connected to %s", safe_url(self._config.streaming_url))

    def _on_message(self, _ws: Any, raw_message: str) -> None:
        """Decode an incoming frame and dispatch it to the handlers on its routes."""
        message = decode_message(raw_message)
        if message is None:
            return
        if WS_ROUTE_ERROR in routes_of(message):
            self._rejection = message
        self._dispatch(message)
        if self._rejection is message and self._ws is not None:
            self._ws.close()  # the server is refusing this socket: leave the loop now

    def _dispatch(self, message: dict[str, Any]) -> None:
        """Hand a decoded frame to every handler on its routes.

        A handler that raises is logged and skipped: it must not break the receive thread.
        """
        _log_ack_error(message)
        for route in routes_of(message):
            for handler in list(self._handlers.get(route, [])):
                try:
                    handler(message)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _log_handler_error(route, e)

    def _on_error(self, _ws: Any, error: Exception) -> None:
        """Remember a handshake failure so the supervisor can react to its HTTP status."""
        status = _handshake_status(error)
        if status is not None and not self._opened.is_set():
            self._handshake_status = status
            return
        logger.error("WebSocket error: %s", type(error).__name__)

    def _on_close(self, _ws: Any, close_status_code: int | None, _close_msg: str | None) -> None:
        """Log the close; the supervisor decides whether to reconnect."""
        self._opened.clear()
        logger.info("WebSocket connection closed (code=%s)", close_status_code)

    def wait(self, timeout: float | None = None) -> None:
        """Block until the supervisor ends (disconnect or unrecoverable error) or timeout.

        Args:
            timeout: Maximum seconds to wait, or None to wait indefinitely.
        """
        thread = self._supervisor
        if thread is None or not thread.is_alive():
            return
        try:
            if timeout is None:
                while thread.is_alive():
                    thread.join(timeout=0.5)
            else:
                deadline = time.monotonic() + timeout
                while thread.is_alive():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    thread.join(timeout=min(0.5, remaining))
        except KeyboardInterrupt:
            logger.info("Interrupted by user (Ctrl+C), disconnecting...")
            self.disconnect()
            raise

    @property
    def is_connected(self) -> bool:
        """Whether a socket is currently open.

        Returns:
            True if the socket is open and the supervisor is running.
        """
        return (
            self._opened.is_set()
            and self._supervisor is not None
            and self._supervisor.is_alive()
        )
