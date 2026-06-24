"""WebSocket client for SSI Streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections.abc import Callable
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
    WS_KEY_CHANNEL,
    WS_THREAD_JOIN_TIMEOUT,
    WS_THREAD_NAME,
)
from ssi_sdk.enums.error import HTTPStatus
from ssi_sdk.exceptions import AuthenticationError, RateLimitError, WebSocketError

logger = logging.getLogger("ssi_sdk.transport.websocket")

MessageHandler = Callable[[dict[str, Any]], Any]


class AsyncWebSocketClient:
    """Async WebSocket client for SSI real-time streaming."""

    def __init__(self, config: Config):
        """Initialize the async WebSocket client with the given configuration."""
        self._config = config
        self._connection: ClientConnection | None = None
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._listen_task: asyncio.Task[None] | None = None
        self._token: str | None = None
        self._running = False
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }

    def set_token(self, token: str) -> None:
        """Set the authentication token for the WebSocket connection.

        Args:
            token: The bearer token used to authenticate the connection.
        """
        self._token = token

    async def connect(self) -> None:
        """Establish a WebSocket connection to the streaming server.

        Raises:
            WebSocketError: If the connection fails after all retry attempts.
        """
        if self._connection is not None:
            return

        url = self._config.streaming_url
        if self._token:
            self._headers[HEADER_AUTHORIZATION] = f"{AUTH_SCHEME_BEARER}{self._token}"

        logger.info("Connecting to WebSocket with headers: %s", self._headers)

        connect_kwargs: dict[str, Any] = {
            "additional_headers": self._headers,
        }
        if self._config.proxy:
            connect_kwargs["proxy"] = self._config.proxy

        max_retries = self._config.max_retries
        delay = self._config.retry_delay
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                self._connection = await ws_async_connect(
                    url,
                    **connect_kwargs,
                )
                self._running = True
                self._listen_task = asyncio.create_task(self._listen())
                logger.info("WebSocket connected to %s", url)
                return
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = delay * (2**attempt)
                    logger.warning(
                        "WebSocket connect attempt %d/%d failed: %s. Retrying in %.1fs",
                        attempt + 1,
                        max_retries,
                        e,
                        wait,
                    )
                    await asyncio.sleep(wait)

        raise WebSocketError(
            f"Failed to connect to {url} after {max_retries} attempts: {last_error}"
        ) from last_error

    async def disconnect(self) -> None:
        """Close the WebSocket connection and stop the listener."""
        self._running = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._connection:
            await self._connection.close()
            self._connection = None
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

        Args:
            data: The message payload to serialize as JSON and send.
        Raises:
            WebSocketError: If not connected or if sending the message fails.
        """
        if not self._connection:
            raise WebSocketError("Not connected. Call connect() first.")
        try:
            await self._connection.send(json.dumps(data))
        except Exception as e:
            raise WebSocketError(f"Failed to send message: {e}") from e

    async def _listen(self) -> None:
        """Internal loop that receives messages and dispatches to handlers."""
        if not self._connection:
            return
        try:
            async for raw_message in self._connection:
                if not self._running:
                    break
                try:
                    message = json.loads(raw_message)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Received non-JSON message: %s", raw_message)
                    continue

                channel = message.get(WS_KEY_CHANNEL, "")
                handlers = self._handlers.get(channel, [])
                for handler in handlers:
                    try:
                        result = handler(message)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.exception("Error in handler for channel '%s': %s", channel, e)
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except asyncio.CancelledError:
            pass
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("WebSocket listen error")
        finally:
            self._running = False
            self._connection = None

    async def wait(self, timeout: float | None = None) -> None:
        """Block until the connection is closed or the timeout elapses.

        Args:
            timeout: Maximum seconds to wait, or None to wait indefinitely.
        """
        if not self._listen_task:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._listen_task), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected.

        Returns:
            True if the connection is open and the listener is running.
        """
        return (
            self._connection is not None
            and self._running
            and self._listen_task is not None
            and not self._listen_task.done()
        )


class WebSocketClient:
    """Synchronous WebSocket client for SSI real-time streaming.

    Uses ``websocket-client`` (sync) with a background listener thread.
    """

    def __init__(self, config: Config):
        """Initialize the sync WebSocket client with the given configuration."""
        self._config = config
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._token: str | None = None
        self._ws: ws_sync.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected_event = threading.Event()
        self._connect_error: Exception | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }

    def set_token(self, token: str) -> None:
        """Set the authentication token for the WebSocket connection.

        Args:
            token: The bearer token used to authenticate the connection.
        """
        self._token = token

    def connect(self) -> None:
        """Establish a WebSocket connection to the streaming server.

        Raises:
            WebSocketError: If the connection fails after all retry attempts.
        """
        if self._running:
            return

        url = self._config.streaming_url
        if self._token:
            self._headers[HEADER_AUTHORIZATION] = f"{AUTH_SCHEME_BEARER}{self._token}"

        header = [f"{k}: {v}" for k, v in self._headers.items()]
        logger.debug("Connecting to WebSocket with headers: %s", header)
        self._ws = ws_sync.WebSocketApp(
            url,
            header=header,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        logger.info("WebSocket connecting to %s", url)
        run_forever_kwargs: dict[str, Any] = {}
        if self._config.proxy:
            run_forever_kwargs["http_proxy_host"] = None
            run_forever_kwargs["http_proxy_port"] = None
            # Parse proxy URL for websocket-client
            parsed = urlparse(self._config.proxy)
            run_forever_kwargs["http_proxy_host"] = parsed.hostname
            run_forever_kwargs["http_proxy_port"] = parsed.port
            if parsed.username:
                run_forever_kwargs["http_proxy_auth"] = (
                    parsed.username,
                    parsed.password,
                )
            if parsed.scheme.startswith("socks"):
                run_forever_kwargs["proxy_type"] = parsed.scheme

        self._connected_event.clear()
        self._connect_error = None
        self._running = True
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs=run_forever_kwargs,
            daemon=True,
            name=WS_THREAD_NAME,
        )
        self._thread.start()
        if not self._connected_event.wait(timeout=self._config.timeout or 30):
            self.disconnect()
            raise WebSocketError(f"Timed out waiting for WebSocket connection to {url}")
        if self._connect_error is not None:
            err = self._connect_error
            self._connect_error = None
            raise err

    def disconnect(self) -> None:
        """Close the WebSocket connection and stop the listener."""
        self._running = False
        self._connected_event.clear()
        ws = self._ws
        if ws:
            ws.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=WS_THREAD_JOIN_TIMEOUT)
        self._ws = None
        self._thread = None
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
        """Send a message through the WebSocket.

        Args:
            data: The message payload to serialize as JSON and send.
        Raises:
            WebSocketError: If not connected or if sending the message fails.
        """
        ws = self._ws
        if not ws or not self._running or not self._connected_event.is_set():
            raise WebSocketError("Not connected. Call connect() first.")
        try:
            ws.send(json.dumps(data))
        except Exception as e:
            raise WebSocketError(f"Failed to send message: {e}") from e

    def _on_open(self, _ws: ws_sync.WebSocketApp) -> None:
        """Signal that the connection is open and unblock connect()."""
        self._connected_event.set()
        logger.info("WebSocket connected to %s", self._config.streaming_url)

    def _on_message(self, _ws: ws_sync.WebSocketApp, raw_message: str) -> None:
        """Parse an incoming message and dispatch it to channel handlers."""
        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Received non-JSON message: %s", raw_message)
            return

        channel = message.get(WS_KEY_CHANNEL, "")
        handlers = self._handlers.get(channel, [])
        for handler in handlers:
            try:
                handler(message)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.exception("Error in handler for channel '%s': %s", channel, e)

    def _on_error(self, _ws: ws_sync.WebSocketApp, error: Exception) -> None:
        """Map a connection error to a typed exception and unblock connect()."""
        error_str = str(error)
        # Extract HTTP status code from handshake error messages like
        # "Handshake status 401 Unauthorized"
        match = re.search(r"Handshake status (\d+)", error_str)
        if match:
            status_code = int(match.group(1))
            try:
                http_status = HTTPStatus(status_code)
            except ValueError:
                http_status = None
            if http_status is not None and http_status.is_auth_error:
                self._connect_error = AuthenticationError(
                    f"WebSocket authentication failed: {status_code}",
                    code=str(status_code),
                    status_code=status_code,
                )
                self._connected_event.set()  # unblock connect()
                return
            if http_status is not None and http_status.is_rate_limit:
                self._connect_error = RateLimitError(
                    "WebSocket rate limit exceeded",
                )
                self._connected_event.set()
                return
            self._connect_error = WebSocketError(
                f"WebSocket handshake failed: {status_code}",
                status_code=status_code,
            )
            self._connected_event.set()
            return
        logger.error("WebSocket error: %s", error)

    def _on_close(
        self,
        _ws: ws_sync.WebSocketApp,
        close_status_code: int | None,
        _close_msg: str | None,
    ) -> None:
        """Mark the client as stopped when the connection closes."""
        self._running = False
        logger.info("WebSocket connection closed (code=%s)", close_status_code)

    def wait(self, timeout: float | None = None) -> None:
        """Block until the connection is closed or the timeout elapses.

        Args:
            timeout: Maximum seconds to wait, or None to wait indefinitely.
        """
        if not self._thread or not self._thread.is_alive():
            return
        try:
            if timeout is None:
                while self._thread.is_alive():
                    self._thread.join(timeout=0.5)
            else:
                deadline = time.monotonic() + timeout
                while self._thread.is_alive():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._thread.join(timeout=min(0.5, remaining))
        except KeyboardInterrupt:
            logger.info("Interrupted by user (Ctrl+C), disconnecting...")
            self.disconnect()
            raise

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected.

        Returns:
            True if the connection is open and the listener is running.
        """
        return self._running and self._connected_event.is_set()
