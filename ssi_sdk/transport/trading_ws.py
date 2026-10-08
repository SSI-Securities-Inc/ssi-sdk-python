"""EXPERIMENTAL: client for the trading WebSocket (``/ws/v3/trading``): orders over a socket.

The server side (``FastConnect.Trading.StreamApi``) has not been announced as released, so this
module is not wired into the ``Trading``/``Stream`` facades; use it only against an
environment you were told supports it. Frame format::

    {"id": "<non-empty>", "method": "order.place", "params": {...},
     "signature": "<base64 or hex>", "timestamp": <epoch ms>}

Rules enforced here:

* ``params`` is serialized **once**; that exact text is signed (RSA-SHA256; base64 by
  default, see ``signature_encoding``) and inserted
  verbatim into the frame. Re-serializing it after signing changes the bytes and the server
  answers 401013.
* Commands that change state (orders, FCO place/cancel) need a private key; without one nothing
  is sent (fail closed). Queries are not signed.
* One id can receive several frames (an immediate ``PD`` ack, later a ``status: 200`` frame
  with the order event), so responses are delivered through a per-id queue.
* A command that times out is **never** retried: it may already have been accepted.
  Reconcile through the ``order.<account>`` event stream or ``query.orderBook``.
* Only ``wss://``. The bearer token goes in the header; params, signatures, tokens and account
  numbers are never logged.
* The server accepts the socket first (HTTP 101) and refuses *afterwards* with a
  ``{"code": 401|403|429|500, "msg": ...}`` frame, so ``connect()`` waits a short grace period
  for it.
* The only config is the domain, ``Config.trading_ws_domain`` (-> ``Config.trading_ws_url``);
  the other tunables are optional keyword arguments of the clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import queue as thread_queue
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

import websocket as ws_sync
from websockets.asyncio.client import connect as ws_async_connect

from ssi_sdk.constant import (
    AUTH_SCHEME_BEARER,
    DEFAULT_USER_AGENT,
    HEADER_AUTHORIZATION,
    HEADER_USER_AGENT,
    MAX_BATCH_ORDERS,
    WS_THREAD_JOIN_TIMEOUT,
)
from ssi_sdk.exceptions import TradingWSError, WebSocketError
from ssi_sdk.transport.websocket_client import _require_wss
from ssi_sdk.utils.crypto import sign

logger = logging.getLogger("ssi_sdk.transport.trading_ws")

SignatureEncoding = Literal["auto", "base64", "hex"]  # what the caller may ask for
WireEncoding = Literal["base64", "hex"]  # what a signature actually is

__all__ = [
    "SignatureEncoding",
    "WireEncoding",
    "AsyncTradingWSClient",
    "MAX_BATCH_ORDERS",
    "MUTATING_METHODS",
    "TradingWSClient",
    "TradingWSError",
    "TradingWSResponse",
]

# Methods the server requires a signature for (matched case-insensitively).
MUTATING_METHODS = frozenset(
    {
        "order.place",
        "order.amend",
        "order.cancel",
        "order.batchnew",
        "order.batchcancel",
        "fco.place",
        "fco.cancel",
    }
)



@dataclass
class TradingWSResponse:
    """A success frame: ``{"id", "method", "status": 200, "result", "rateLimit", ...}``."""

    id: str = ""
    method: str = ""
    status: int = 200
    result: Any = None
    rate_limit: dict[str, Any] = field(default_factory=dict)
    received_time: int | None = None

    @classmethod
    def from_frame(cls, frame: dict[str, Any]) -> TradingWSResponse:
        """Build a response from a decoded frame; every key is optional."""
        rate_limit = frame.get("rateLimit")
        try:
            status = int(frame.get("status", 200))
        except (TypeError, ValueError):
            status = 200
        return cls(
            id=str(frame.get("id") or ""),
            method=str(frame.get("method") or ""),
            status=status,
            result=frame.get("result"),
            rate_limit=rate_limit if isinstance(rate_limit, dict) else {},
            received_time=frame.get("receivedTime"),
        )


def _json_number(value: Any) -> Any:
    """``json.dumps`` hook: a ``Decimal`` goes out as a plain JSON number (int if whole)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_command(
    method: str,
    params: dict[str, Any],
    private_key: str | None,
    request_id: str,
    timestamp: float,
    encoding: WireEncoding = "base64",
) -> str:
    """Build the text of one command frame.

    ``params`` is serialized once; the same text is signed and then inserted as is.

    Raises:
        WebSocketError: If the method needs a signature and there is no private key, or the
            id is empty.
    """
    if not request_id:
        raise WebSocketError("a command needs a non-empty id")
    params_text = json.dumps(
        params, separators=(",", ":"), ensure_ascii=False, default=_json_number
    )
    signature_part = ""
    if method.lower() in MUTATING_METHODS:
        if not private_key:
            raise WebSocketError("private_key is required for trading commands that change state")
        signature_part = ',"signature":' + json.dumps(sign(params_text, private_key, encoding))
    return (
        '{"id":'
        + json.dumps(request_id)
        + ',"method":'
        + json.dumps(method)
        + ',"params":'
        + params_text
        + signature_part
        + ',"timestamp":'
        + str(int(timestamp))
        + "}"
    )


_SIGNATURE_CODES = {"401006", "401008", "401013"}


def unwrap(frame: dict[str, Any], encoding_hint: str | None = None) -> dict[str, Any]:
    """Return a success frame, or raise :class:`TradingWSError` for an error frame.

    Error frames look like ``{"id", "status": 4xx | "error", "error": {"code", "message"}}``
    (``fco.*`` answers ``status: "error"`` with ``error.code: "FCO_ERROR"``).
    """
    error = frame.get("error")
    try:
        status = int(frame.get("status", 200))
    except (TypeError, ValueError):
        status = 0  # "error"
    if error or status >= 400:
        detail = error if isinstance(error, dict) else {}
        code, message = str(detail.get("code", "")), str(detail.get("message", ""))
        if encoding_hint and code in _SIGNATURE_CODES:
            other = "hex" if encoding_hint == "base64" else "base64"
            message += (
                f" (signature rejected: signed as {encoding_hint}; if every signed command fails "
                f"this way pass signature_encoding={other!r} to the trading WS client)"
            )
        raise TradingWSError(status, code, message)
    return frame


def _both_refused(error: TradingWSError) -> TradingWSError:
    """The error to raise when the server refused the signature in both encodings."""
    return TradingWSError(
        error.status,
        error.error_code,
        f"{error.server_message} (refused with a base64 and a hex signature: check that "
        "Config.private_key is the key registered for this API key)",
    )


def is_rejection(frame: dict[str, Any]) -> bool:
    """A post-upgrade refusal: ``{"code": 401|403|429|500, "msg": ...}`` with no ``id``."""
    return "id" not in frame and "code" in frame and ("msg" in frame or "message" in frame)


def rejection_error(frame: dict[str, Any]) -> TradingWSError:
    """The error for a refusal frame (401 token, 403 missing ``tradingws:*:*``, 429 limit)."""
    try:
        status = int(frame.get("code") or 0)
    except (TypeError, ValueError):
        status = 0
    message = str(frame.get("msg") or frame.get("message") or "")
    return TradingWSError(status, str(frame.get("code", "")), message)


def _decode(raw: Any) -> dict[str, Any] | None:
    """Decode a frame; anything that is not a JSON object is dropped (content never logged)."""
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Dropped a non-JSON trading frame (%d bytes)", len(raw or ""))
        return None
    return frame if isinstance(frame, dict) else None


# ── async ────────────────────────────────────────────────────


class AsyncTradingWSClient:
    """Async client for the trading WebSocket (EXPERIMENTAL, see the module docstring)."""

    def __init__(
        self,
        url: str,
        token_provider: Callable[[], Any],
        private_key: str | None = None,
        *,
        request_timeout: float = 10.0,
        signature_encoding: SignatureEncoding = "auto",
        handshake_grace: float = 0.5,
        respect_rate_limit: bool = True,
        max_rate_limit_wait: float = 2.0,
        ping_interval: float | None = 30.0,
        user_agent: str | None = None,
        connect_fn: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        """Create the client.

        Args:
            url: ``wss://<domain>/ws/v3/trading`` (``Config.trading_ws_url``).
            token_provider: Returns the access token (sync or async), called on ``connect``.
            private_key: Key for signing state-changing commands (``Config.private_key``).
            request_timeout: Seconds to wait for a response before giving up (no retry).
            signature_encoding: ``"auto"`` (default): sign as base64 (what the public documentation
                states) and, if the server refuses a command's signature (401006/401008/401013 --
                the command was not executed), send it once more as hex (what REST uses) and keep
                whichever works. ``"base64"`` / ``"hex"`` fix the encoding.
            handshake_grace: Seconds ``connect()`` waits after the upgrade for the refusal frame the
                server sends *after* HTTP 101 (``{"code": 401|403|429|500, "msg": ...}``); 0 skips.
            respect_rate_limit: After a response with ``remaining == 0`` wait for its ``resetMs``
                (at most ``max_rate_limit_wait``) before the next command, instead of getting a 429.
            max_rate_limit_wait: Upper bound in seconds for that wait.
            ping_interval: Send ``ping_pong`` this often (seconds) to notice a hung connection
                early; ``None`` disables it.
            user_agent: ``User-Agent`` of the upgrade request (default: the SDK's browser-like one;
                the gateway's firewall answers 403 to the bare library one).
            connect_fn: Coroutine factory that opens the socket (tests inject a fake).
            clock: Epoch-seconds clock for the command timestamp.
            sleep_fn: Awaitable sleep (tests inject a fake).
        Raises:
            WebSocketError: If ``url`` is not ``wss://``.
        """
        _require_wss(url)
        self._url = url
        self._token_provider = token_provider
        self._private_key = private_key
        self._timeout = request_timeout
        self._connect_fn = connect_fn or ws_async_connect
        self._clock = clock or time.time
        self._ws: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._sleep = sleep_fn or asyncio.sleep
        self._auto = signature_encoding == "auto"
        self._encoding: WireEncoding = (
            "base64" if signature_encoding == "auto" else signature_encoding
        )
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._grace = handshake_grace
        self._respect_rate_limit = respect_rate_limit
        self._max_rate_wait = max_rate_limit_wait
        self._ping_interval = ping_interval
        self._rejection: TradingWSError | None = None
        self._blocked_until = 0.0
        self._pending: dict[str, asyncio.Queue] = {}
        self.on_event: Callable[[dict[str, Any]], Any] | None = None
        self.rate_limit: dict[str, Any] = {}

    async def connect(self) -> None:
        """Open the socket with the bearer token in the header."""
        if self._ws is not None:
            return
        token = self._token_provider()
        if inspect.isawaitable(token):
            token = await token
        self._rejection = None
        self._ws = await self._connect_fn(
            self._url,
            additional_headers={
                HEADER_AUTHORIZATION: f"{AUTH_SCHEME_BEARER}{token}",
                HEADER_USER_AGENT: self._user_agent,
            },
        )
        self._reader = asyncio.create_task(self._read_loop())
        # The server accepts the socket (101) and refuses afterwards: give that frame time to show.
        waited = 0.0
        while waited < self._grace and self._rejection is None and not self._reader.done():
            await self._sleep(0.05)
            waited += 0.05
        if self._rejection is not None:
            error = self._rejection
            await self.close()
            raise error
        if self._ping_interval:
            self._ping_task = asyncio.create_task(self._ping_loop())

    async def _ping_loop(self) -> None:
        """Keep-alive: ping periodically so a hung connection is noticed early."""
        interval = self._ping_interval or 0.0
        try:
            while True:
                await self._sleep(interval)
                try:
                    await self.ping()
                except WebSocketError:
                    return
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        """Close the socket and wake every waiter."""
        ping, self._ping_task = self._ping_task, None
        if ping is not None:
            ping.cancel()
            await asyncio.gather(ping, return_exceptions=True)
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        self._fail_pending()

    def _fail_pending(self, error: TradingWSError | None = None) -> None:
        for waiting in self._pending.values():
            waiting.put_nowait(error)  # wakes the waiter: refused, or the connection is gone
        self._pending.clear()

    @property
    def is_connected(self) -> bool:
        """Whether the socket is open and the reader is running."""
        return self._ws is not None and self._reader is not None and not self._reader.done()

    @property
    def rejection(self) -> TradingWSError | None:
        """The refusal the server sent after the upgrade (401/403/429/500), if any."""
        return self._rejection

    def _new_id(self) -> str:
        while True:
            request_id = secrets.token_hex(8)  # CSPRNG
            if request_id not in self._pending:
                return request_id

    async def request_stream(self, method: str, params: dict[str, Any]) -> asyncio.Queue:
        """Send one command and return the queue that receives **every** frame with its id.

        The caller owns the queue and should release it with :meth:`forget` (or use
        :meth:`stream`). A ``None`` item means the connection closed; a
        :class:`TradingWSError` item means the server refused the connection.

        Raises:
            WebSocketError: If not connected, or a state-changing command has no private key.
        """
        if self._rejection is not None:
            raise self._rejection
        if self._ws is None:
            raise WebSocketError("not connected")
        if self._respect_rate_limit and self._blocked_until > self._clock():
            await self._sleep(self._blocked_until - self._clock())
        request_id = self._new_id()
        raw = build_command(
            method, params, self._private_key, request_id, self._clock() * 1000, self._encoding
        )
        waiting: asyncio.Queue = asyncio.Queue()
        self._pending[request_id] = waiting
        try:
            await self._ws.send(raw)
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise WebSocketError(f"failed to send {method}: {type(exc).__name__}") from exc
        return waiting

    async def subscribe(self, channel: str, topics: list[str]) -> None:
        """Send a subscription frame (no ``id``, so the server treats it as a subscription).

        The ack ``{"method", "channel", "status", "message"}`` and the later events
        ``{"channel", "topic", "data"}`` carry no command id, so they arrive on ``on_event``.
        ``order.<account>`` requires an account the token owns (else the ack is ``Denied``).

        Raises:
            WebSocketError: If not connected.
        """
        await self._send_subscription("SUBSCRIBE", channel, topics)

    async def unsubscribe(self, channel: str, topics: list[str]) -> None:
        """Remove topics subscribed with :meth:`subscribe`."""
        await self._send_subscription("UNSUBSCRIBE", channel, topics)

    async def ping(self) -> None:
        """Send ``PING_PONG``; the ack arrives on ``on_event``."""
        await self._send_frame({"method": "PING_PONG"})

    async def _send_subscription(self, method: str, channel: str, topics: list[str]) -> None:
        await self._send_frame({"method": method, "channel": channel, "topics": list(topics)})

    async def _send_frame(self, frame: dict[str, Any]) -> None:
        if self._ws is None:
            raise WebSocketError("not connected")
        try:
            await self._ws.send(json.dumps(frame))
        except Exception as exc:
            raise WebSocketError(f"failed to send: {type(exc).__name__}") from exc

    def forget(self, waiting: asyncio.Queue) -> None:
        """Stop routing frames to ``waiting``; later frames with that id go to ``on_event``."""
        for key, value in list(self._pending.items()):
            if value is waiting:
                del self._pending[key]

    @contextlib.asynccontextmanager
    async def stream(self, method: str, params: dict[str, Any]) -> AsyncIterator[asyncio.Queue]:
        """Send a command and yield its queue; the queue is released on exit."""
        waiting = await self.request_stream(method, params)
        try:
            yield waiting
        finally:
            self.forget(waiting)

    async def next_response(
        self, waiting: asyncio.Queue, timeout: float | None = None
    ) -> TradingWSResponse:
        """Take the next frame from a command queue.

        Raises:
            TradingWSError: For an error frame.
            WebSocketError: On timeout (the command is NOT retried) or a closed connection.
        """
        try:
            frame = await asyncio.wait_for(waiting.get(), timeout or self._timeout)
        except asyncio.TimeoutError as exc:
            raise WebSocketError("timed out waiting for a response (not retried)") from exc
        if isinstance(frame, TradingWSError):
            raise frame
        if frame is None:
            raise WebSocketError("connection closed before the response arrived")
        hint = None if self._auto else self._encoding
        response = TradingWSResponse.from_frame(unwrap(frame, hint))
        self._note_rate_limit(response.rate_limit)
        return response

    def _note_rate_limit(self, rate_limit: dict[str, Any]) -> None:
        """Remember the quota; at ``remaining == 0`` hold the next command until the reset."""
        if not rate_limit:
            return
        self.rate_limit = rate_limit
        if rate_limit.get("remaining") == 0:
            reset = min(float(rate_limit.get("resetMs") or 0) / 1000, self._max_rate_wait)
            self._blocked_until = self._clock() + reset

    def _other_encoding(self, method: str, error: TradingWSError) -> WireEncoding | None:
        """The encoding to retry with, or None: only in auto mode, for a signed command whose
        signature the server refused."""
        if not (self._auto and method.lower() in MUTATING_METHODS):
            return None
        if error.error_code not in _SIGNATURE_CODES:
            return None
        return "hex" if self._encoding == "base64" else "base64"

    async def request(self, method: str, params: dict[str, Any]) -> TradingWSResponse:
        """Send one command and return its **first** response frame (the ack).

        For ``order.*`` the ack is ``orderStatus: "PD"``; the final result arrives later on
        ``order.<account>`` events. Use :meth:`stream` to also see the second frame with the
        same id. Never retried.
        """
        try:
            async with self.stream(method, params) as waiting:
                return await self.next_response(waiting)
        except TradingWSError as exc:
            other = self._other_encoding(method, exc)
            if other is None:
                raise
        # The server refused the signature, so the command was NOT executed: try the other form.
        first, self._encoding = self._encoding, other
        try:
            async with self.stream(method, params) as waiting:
                return await self.next_response(waiting)
        except TradingWSError as second:
            self._encoding = first
            raise _both_refused(second) from None

    async def _read_loop(self) -> None:
        try:
            async for message in self._ws:
                frame = _decode(message)
                if frame is None:
                    continue
                if is_rejection(frame):
                    self._rejection = rejection_error(frame)
                    self._fail_pending(self._rejection)
                    continue
                request_id = frame.get("id")
                waiting = self._pending.get(request_id) if isinstance(request_id, str) else None
                if waiting is not None:
                    waiting.put_nowait(frame)
                elif self.on_event is not None:
                    try:
                        result = self.on_event(frame)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:  # pylint: disable=broad-exception-caught
                        logger.exception("Error in the on_event handler")
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Trading WebSocket reader ended", exc_info=True)
        finally:
            self._fail_pending()


# ── sync ─────────────────────────────────────────────────────


class TradingWSClient:
    """Synchronous client for the trading WebSocket (EXPERIMENTAL, see the module docstring)."""

    def __init__(
        self,
        url: str,
        token_provider: Callable[[], str],
        private_key: str | None = None,
        *,
        request_timeout: float = 10.0,
        signature_encoding: SignatureEncoding = "auto",
        handshake_grace: float = 0.5,
        respect_rate_limit: bool = True,
        max_rate_limit_wait: float = 2.0,
        ping_interval: float | None = 30.0,
        user_agent: str | None = None,
        connect_fn: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        """Create the client (same arguments as :class:`AsyncTradingWSClient`).

        Raises:
            WebSocketError: If ``url`` is not ``wss://``.
        """
        _require_wss(url)
        self._url = url
        self._token_provider = token_provider
        self._private_key = private_key
        self._timeout = request_timeout
        self._connect_fn = connect_fn or ws_sync.create_connection
        self._clock = clock or time.time
        self._sleep = sleep_fn or time.sleep
        self._auto = signature_encoding == "auto"
        self._encoding: WireEncoding = (
            "base64" if signature_encoding == "auto" else signature_encoding
        )
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._grace = handshake_grace
        self._respect_rate_limit = respect_rate_limit
        self._max_rate_wait = max_rate_limit_wait
        self._ping_interval = ping_interval
        self._rejection: TradingWSError | None = None
        self._blocked_until = 0.0
        self._stop = threading.Event()
        self._ws: Any = None
        self._reader: threading.Thread | None = None
        self._pinger: threading.Thread | None = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending: dict[str, thread_queue.Queue] = {}
        self._closing = False
        self.on_event: Callable[[dict[str, Any]], Any] | None = None
        self.rate_limit: dict[str, Any] = {}

    def connect(self) -> None:
        """Open the socket with the bearer token in the header."""
        if self._ws is not None:
            return
        token = self._token_provider()
        self._closing = False
        self._rejection = None
        self._stop.clear()
        self._ws = self._connect_fn(
            self._url,
            header=[
                f"{HEADER_AUTHORIZATION}: {AUTH_SCHEME_BEARER}{token}",
                f"{HEADER_USER_AGENT}: {self._user_agent}",
            ],
            timeout=self._timeout,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="ssi-trading-ws")
        self._reader.start()
        # The server accepts the socket (101) and refuses afterwards: give that frame time to show.
        waited = 0.0
        while waited < self._grace and self._rejection is None and self._reader.is_alive():
            self._sleep(0.05)
            waited += 0.05
        if self._rejection is not None:
            error = self._rejection
            self.close()
            raise error
        if self._ping_interval:
            self._pinger = threading.Thread(
                target=self._ping_loop, daemon=True, name="ssi-trading-ws-ping"
            )
            self._pinger.start()

    def _ping_loop(self) -> None:
        """Keep-alive: ping periodically so a hung connection is noticed early."""
        while not self._stop.wait(self._ping_interval):
            try:
                self.ping()
            except WebSocketError:
                return

    def close(self) -> None:
        """Close the socket, stop the reader and wake every waiter."""
        self._closing = True
        self._stop.set()
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                ws.close()
        pinger, self._pinger = self._pinger, None
        if pinger is not None and pinger is not threading.current_thread():
            pinger.join(timeout=WS_THREAD_JOIN_TIMEOUT)
        reader, self._reader = self._reader, None
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=WS_THREAD_JOIN_TIMEOUT)
        self._fail_pending()

    def _fail_pending(self, error: TradingWSError | None = None) -> None:
        with self._lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for item in waiting:
            item.put(error)  # wakes the waiter: refused, or the connection is gone

    @property
    def is_connected(self) -> bool:
        """Whether the socket is open and the reader is running."""
        return self._ws is not None and self._reader is not None and self._reader.is_alive()

    @property
    def rejection(self) -> TradingWSError | None:
        """The refusal the server sent after the upgrade (401/403/429/500), if any."""
        return self._rejection

    def _new_id(self) -> str:
        while True:
            request_id = secrets.token_hex(8)  # CSPRNG
            if request_id not in self._pending:
                return request_id

    def request_stream(self, method: str, params: dict[str, Any]) -> thread_queue.Queue:
        """Send one command and return the queue that receives **every** frame with its id.

        The caller owns the queue and should release it with :meth:`forget` (or use
        :meth:`stream`). A ``None`` item means the connection closed; a
        :class:`TradingWSError` item means the server refused the connection.

        Raises:
            WebSocketError: If not connected, or a state-changing command has no private key.
        """
        if self._rejection is not None:
            raise self._rejection
        ws = self._ws
        if ws is None:
            raise WebSocketError("not connected")
        if self._respect_rate_limit and self._blocked_until > self._clock():
            self._sleep(self._blocked_until - self._clock())
        waiting: thread_queue.Queue = thread_queue.Queue()
        with self._lock:
            request_id = self._new_id()
            raw = build_command(
                method, params, self._private_key, request_id, self._clock() * 1000, self._encoding
            )
            self._pending[request_id] = waiting
        try:
            with self._send_lock:
                ws.send(raw)
        except Exception as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise WebSocketError(f"failed to send {method}: {type(exc).__name__}") from exc
        return waiting

    def subscribe(self, channel: str, topics: list[str]) -> None:
        """Send a subscription frame (no ``id``, so the server treats it as a subscription).

        The ack ``{"method", "channel", "status", "message"}`` and the later events
        ``{"channel", "topic", "data"}`` carry no command id, so they arrive on ``on_event``.
        ``order.<account>`` requires an account the token owns (else the ack is ``Denied``).

        Raises:
            WebSocketError: If not connected.
        """
        self._send_frame({"method": "SUBSCRIBE", "channel": channel, "topics": list(topics)})

    def unsubscribe(self, channel: str, topics: list[str]) -> None:
        """Remove topics subscribed with :meth:`subscribe`."""
        self._send_frame({"method": "UNSUBSCRIBE", "channel": channel, "topics": list(topics)})

    def ping(self) -> None:
        """Send ``PING_PONG``; the ack arrives on ``on_event``."""
        self._send_frame({"method": "PING_PONG"})

    def _send_frame(self, frame: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise WebSocketError("not connected")
        try:
            with self._send_lock:
                ws.send(json.dumps(frame))
        except Exception as exc:
            raise WebSocketError(f"failed to send: {type(exc).__name__}") from exc

    def forget(self, waiting: thread_queue.Queue) -> None:
        """Stop routing frames to ``waiting``; later frames with that id go to ``on_event``."""
        with self._lock:
            for key, value in list(self._pending.items()):
                if value is waiting:
                    del self._pending[key]

    @contextlib.contextmanager
    def stream(self, method: str, params: dict[str, Any]) -> Iterator[thread_queue.Queue]:
        """Send a command and yield its queue; the queue is released on exit."""
        waiting = self.request_stream(method, params)
        try:
            yield waiting
        finally:
            self.forget(waiting)

    def next_response(
        self, waiting: thread_queue.Queue, timeout: float | None = None
    ) -> TradingWSResponse:
        """Take the next frame from a command queue.

        Raises:
            TradingWSError: For an error frame.
            WebSocketError: On timeout (the command is NOT retried) or a closed connection.
        """
        try:
            frame = waiting.get(timeout=timeout or self._timeout)
        except thread_queue.Empty as exc:
            raise WebSocketError("timed out waiting for a response (not retried)") from exc
        if isinstance(frame, TradingWSError):
            raise frame
        if frame is None:
            raise WebSocketError("connection closed before the response arrived")
        hint = None if self._auto else self._encoding
        response = TradingWSResponse.from_frame(unwrap(frame, hint))
        self._note_rate_limit(response.rate_limit)
        return response

    def _note_rate_limit(self, rate_limit: dict[str, Any]) -> None:
        """Remember the quota; at ``remaining == 0`` hold the next command until the reset."""
        if not rate_limit:
            return
        self.rate_limit = rate_limit
        if rate_limit.get("remaining") == 0:
            reset = min(float(rate_limit.get("resetMs") or 0) / 1000, self._max_rate_wait)
            self._blocked_until = self._clock() + reset

    def _other_encoding(self, method: str, error: TradingWSError) -> WireEncoding | None:
        """The encoding to retry with, or None: only in auto mode, for a signed command whose
        signature the server refused."""
        if not (self._auto and method.lower() in MUTATING_METHODS):
            return None
        if error.error_code not in _SIGNATURE_CODES:
            return None
        return "hex" if self._encoding == "base64" else "base64"

    def request(self, method: str, params: dict[str, Any]) -> TradingWSResponse:
        """Send one command and return its **first** response frame (the ack). Never retried."""
        try:
            with self.stream(method, params) as waiting:
                return self.next_response(waiting)
        except TradingWSError as exc:
            other = self._other_encoding(method, exc)
            if other is None:
                raise
        # The server refused the signature, so the command was NOT executed: try the other form.
        first, self._encoding = self._encoding, other
        try:
            with self.stream(method, params) as waiting:
                return self.next_response(waiting)
        except TradingWSError as second:
            self._encoding = first
            raise _both_refused(second) from None

    def _read_loop(self) -> None:
        ws = self._ws
        try:
            while ws is not None and not self._closing:
                frame = _decode(ws.recv())
                if frame is None:
                    continue
                if is_rejection(frame):
                    self._rejection = rejection_error(frame)
                    self._fail_pending(self._rejection)
                    continue
                request_id = frame.get("id")
                with self._lock:
                    waiting = self._pending.get(request_id) if isinstance(request_id, str) else None
                if waiting is not None:
                    waiting.put(frame)
                elif self.on_event is not None:
                    try:
                        self.on_event(frame)
                    except Exception:  # pylint: disable=broad-exception-caught
                        logger.exception("Error in the on_event handler")
        except Exception:  # pylint: disable=broad-exception-caught
            if not self._closing:  # a close() we asked for is not worth a traceback
                logger.debug("Trading WebSocket reader ended", exc_info=True)
        finally:
            self._fail_pending()
