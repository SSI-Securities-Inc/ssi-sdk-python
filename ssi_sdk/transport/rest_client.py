"""REST client for SSI API (async and sync)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    AUTH_SCHEME_BEARER,
    CONTENT_TYPE_JSON,
    DEFAULT_USER_AGENT,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    HEADER_CONTENT_TYPE,
    HEADER_RATE_LIMIT_LIMIT,
    HEADER_RATE_LIMIT_REMAINING,
    HEADER_RETRY_AFTER,
    HEADER_USER_AGENT,
    HTTP_STATUS_CONFLICT,
    RATE_LIMIT_DEFAULT_WAIT,
    RATE_LIMIT_MAX_RETRIES,
    RATE_LIMIT_MAX_WAIT,
    SMART_OTP_PENDING_CODE,
    SMART_OTP_PENDING_STATUS,
    SMART_OTP_TERMINAL_CODES,
    TRADING_API_PATH_PREFIXES,
)
from ssi_sdk.enums import HTTPStatus
from ssi_sdk.exceptions import (
    APIError,
    AuthenticationError,
    DuplicateRequestError,
    RateLimitError,
    SmartOTPPendingError,
    SmartOTPRejectedError,
    SSIError,
)
from ssi_sdk.utils.redact import redact
from ssi_sdk.utils.retry import RateLimiter, retry_async, retry_sync

logger = logging.getLogger("ssi_sdk.transport.rest")


def _json_or_none(response: httpx.Response) -> Any:
    """Parse the response body as JSON, or None when it is empty or not JSON."""
    try:
        return response.json()
    except ValueError:
        return None


def _int_or_none(value: Any) -> int | None:
    """Parse an int from a header/body value without raising."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse ``Retry-After`` (delta-seconds); an HTTP-date or garbage yields None."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _server_code(body: Any) -> int | str | None:
    """Return the server's ``code`` from a ``{code, msg}`` body (int when numeric)."""
    if not isinstance(body, dict) or body.get("code") is None:
        return None
    code = body["code"]
    as_int = _int_or_none(code)
    return as_int if as_int is not None else str(code)


def _server_message(body: Any, text: str) -> str:
    """Return the server's ``msg``/``message``, else a short slice of the raw text."""
    if isinstance(body, dict):
        for key in ("msg", "message"):
            if body.get(key):
                return str(body[key])
    return text[:200]


def _error_for(response: httpx.Response, body: Any) -> SSIError:
    """Build the exception for a non-2xx response.

    The message carries only the server's code and msg, never the raw body or URL.
    """
    status = response.status_code
    code = _server_code(body)
    detail = _server_message(body, response.text)
    message = f"API error {status}" + (f" [{code}]" if code is not None else "")
    if detail:
        message = f"{message}: {detail}"
    kwargs: dict[str, Any] = {
        "status_code": status,
        "response_body": redact(body) if isinstance(body, dict) else None,
        "headers": dict(response.headers),
    }
    shown_code = code if code is not None else str(status)

    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return RateLimitError(
            message,
            retry_after=_retry_after_seconds(response.headers.get(HEADER_RETRY_AFTER)),
            code=shown_code,
            limit=_int_or_none(response.headers.get(HEADER_RATE_LIMIT_LIMIT)),
            remaining=_int_or_none(response.headers.get(HEADER_RATE_LIMIT_REMAINING)),
            **kwargs,
        )
    if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        if code in SMART_OTP_TERMINAL_CODES:
            return SmartOTPRejectedError(message, shown_code, **kwargs)
        return AuthenticationError(message, shown_code, **kwargs)
    if status == HTTP_STATUS_CONFLICT:
        return DuplicateRequestError(message, shown_code, **kwargs)
    return APIError(message, shown_code, **kwargs)


def _handle_response(response: httpx.Response) -> Any:
    """Parse and validate an HTTP response.

    Order matters: a pending Smart OTP arrives as HTTP 202 (not an error status), and a
    failure can arrive as HTTP 200 with a ``{code, msg}`` body.

    Returns:
        The parsed body. An empty result is ``{"code": 204, ...}`` (see ``is_no_content``).
    Raises:
        SmartOTPPendingError: HTTP 202 carrying code 401114.
        AuthenticationError / RateLimitError / DuplicateRequestError / APIError: non-2xx
            status, or a 2xx body whose ``code`` is neither 200 nor 204.
    """
    status = response.status_code
    if status >= HTTPStatus.BAD_REQUEST:
        raise _error_for(response, _json_or_none(response))

    if status == HTTPStatus.NO_CONTENT:
        return {}

    body = _json_or_none(response)
    if status == SMART_OTP_PENDING_STATUS and _server_code(body) == SMART_OTP_PENDING_CODE:
        raise SmartOTPPendingError(
            f"Smart OTP approval pending [{SMART_OTP_PENDING_CODE}]: {_server_message(body, '')}",
            SMART_OTP_PENDING_CODE,
            status_code=status,
            response_body=redact(body),
            headers=dict(response.headers),
        )
    if body is None:
        raise APIError(
            f"API returned a non-JSON body (HTTP {status})",
            code=str(status),
            status_code=status,
            headers=dict(response.headers),
        )
    if isinstance(body, dict) and ("msg" in body or "message" in body):
        code = _int_or_none(body.get("code"))
        if code is not None and code not in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
            raise _error_for(response, body)
    return body


def _route(config: Config, path: str) -> str:
    """The URL to request: ``path`` as is, or on the trading host for trading/account paths.

    Only when ``Config.trading_api_domain`` is set and differs from ``api_url``; the client's
    headers (bearer token) still apply, and the same rate limiter is shared.
    """
    if config.trading_api_domain and path.startswith(TRADING_API_PATH_PREFIXES):
        base = config.trading_api_url
        if base != config.api_url.rstrip("/"):
            return base + path
    return path


def _rate_wait(error: RateLimitError, attempt: int) -> float | None:
    """How long to wait after a 429 (``Retry-After``, else 1s doubling), or None to give up."""
    wait = error.retry_after if error.retry_after else RATE_LIMIT_DEFAULT_WAIT * (2**attempt)
    return wait if wait <= RATE_LIMIT_MAX_WAIT else None


def _observe_rate_limit(limiter: RateLimiter, response: httpx.Response) -> dict[str, int | None]:
    """Follow the server's quota headers: never exceed ``X-RateLimit-Limit`` per second, and rest
    for a second when ``X-RateLimit-Remaining`` hits 0. Returns the numbers seen."""
    seen = {
        "limit": _int_or_none(response.headers.get(HEADER_RATE_LIMIT_LIMIT)),
        "remaining": _int_or_none(response.headers.get(HEADER_RATE_LIMIT_REMAINING)),
    }
    if seen["limit"] is not None:
        limiter.cap(seen["limit"])
    if seen["remaining"] == 0:
        limiter.pause(1.0)
    return seen


def _should_retry(method: str, retry: bool | None) -> bool:
    """Whether a request may be replayed after a timeout (GET only unless forced)."""
    return method.upper() == "GET" if retry is None else retry


class AsyncRestClient:
    """Async HTTP client for SSI REST API."""

    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None):
        """Initialize the async REST client with the given configuration.

        Args:
            config: SDK configuration.
            transport: Optional httpx transport (used by tests to inject a mock).
        """
        self._config = config
        self._transport = transport
        self._rate_limiter = RateLimiter(config.rate_limit_per_second)
        self.rate_limit: dict[str, int | None] = {}  # last X-RateLimit-Limit / -Remaining seen
        self._client: httpx.AsyncClient | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
            HEADER_USER_AGENT: config.user_agent or DEFAULT_USER_AGENT,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the cached HTTP client, lazily creating it if needed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._config.api_url,
                timeout=self._config.timeout,
                headers=self._headers,
                proxy=self._config.proxy,
                transport=self._transport,
            )
        return self._client

    @property
    def config(self) -> Config:
        """The SDK configuration this client was built with."""
        return self._config

    def clear_auth_header(self) -> None:
        """Drop the bearer token so a dead token is no longer sent."""
        self._headers.pop(HEADER_AUTHORIZATION, None)
        if self._client is not None and not self._client.is_closed:
            self._client.headers.pop(HEADER_AUTHORIZATION, None)

    def get_private_key(self) -> str:
        """Get the private key used for signing requests.

        Returns:
            The configured private key string.
        """
        return self._config.private_key

    def set_auth_header(self, token: str) -> None:
        """Update the authorization header with a bearer token.

        Args:
            token: The bearer token to set on outgoing requests.
        """
        self._headers[HEADER_AUTHORIZATION] = f"{AUTH_SCHEME_BEARER}{token}"
        # Update the live client's headers in place — recreating it would leak
        # the open connection pool.
        if self._client is not None and not self._client.is_closed:
            self._client.headers[HEADER_AUTHORIZATION] = self._headers[HEADER_AUTHORIZATION]

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
        retry: bool | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated async HTTP request.

        Args:
            method: The HTTP verb to use (e.g. ``GET``, ``POST``).
            path: The endpoint path appended to the base API URL.
            params: Optional query parameters.
            json_body: Optional JSON payload to send as the request body.
            data: Optional form-encoded data to send as the request body.
            content: Optional raw request body (e.g. signed orders).
            headers: Optional extra headers merged into the request.
            retry: Retry on timeout with backoff. Defaults to True for GET and False for
                every other verb: a timed-out POST/PUT/DELETE may already have been
                processed (an order, an OTP), so replaying it is not safe.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        url = _route(self._config, path)
        replayable = _should_retry(method, retry)

        async def _do_request() -> dict[str, Any]:
            client = await self._get_client()
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                content=content,
                headers=headers,
            )
            self.rate_limit = _observe_rate_limit(self._rate_limiter, response)
            return _handle_response(response)

        attempt = 0
        while True:
            await self._rate_limiter.async_acquire()
            try:
                if not replayable:
                    return await _do_request()
                return await retry_async(
                    _do_request,
                    max_retries=self._config.max_retries,
                    delay=self._config.retry_delay,
                )
            except RateLimitError as exc:
                wait = _rate_wait(exc, attempt)
                if not replayable or wait is None or attempt >= RATE_LIMIT_MAX_RETRIES:
                    raise
                logger.info("429 on %s: waiting %.1fs (attempt %d)", path, wait, attempt + 1)
                self._rate_limiter.pause(wait)
                attempt += 1

    async def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a GET request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a POST request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a PUT request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a DELETE request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return await self.request("DELETE", path, **kwargs)

    async def close(self) -> None:
        """Close the underlying HTTP client and release its connections."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class RestClient:
    """Synchronous HTTP client for SSI REST API."""

    def __init__(self, config: Config, transport: httpx.BaseTransport | None = None):
        """Initialize the sync REST client with the given configuration.

        Args:
            config: SDK configuration.
            transport: Optional httpx transport (used by tests to inject a mock).
        """
        self._config = config
        self._transport = transport
        self._rate_limiter = RateLimiter(config.rate_limit_per_second)
        self.rate_limit: dict[str, int | None] = {}  # last X-RateLimit-Limit / -Remaining seen
        self._client: httpx.Client | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
            HEADER_USER_AGENT: config.user_agent or DEFAULT_USER_AGENT,
        }

    def _get_client(self) -> httpx.Client:
        """Return the cached HTTP client, lazily creating it if needed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self._config.api_url,
                timeout=self._config.timeout,
                headers=self._headers,
                proxy=self._config.proxy,
                transport=self._transport,
            )
        return self._client

    @property
    def config(self) -> Config:
        """The SDK configuration this client was built with."""
        return self._config

    def clear_auth_header(self) -> None:
        """Drop the bearer token so a dead token is no longer sent."""
        self._headers.pop(HEADER_AUTHORIZATION, None)
        if self._client is not None and not self._client.is_closed:
            self._client.headers.pop(HEADER_AUTHORIZATION, None)

    def get_private_key(self) -> str:
        """Get the private key used for signing requests.

        Returns:
            The configured private key string.
        """
        return self._config.private_key

    def set_auth_header(self, token: str) -> None:
        """Update the authorization header with a bearer token.

        Args:
            token: The bearer token to set on outgoing requests.
        """
        self._headers[HEADER_AUTHORIZATION] = f"{AUTH_SCHEME_BEARER}{token}"
        # Update the live client's headers in place — recreating it would leak
        # the open connection pool.
        if self._client is not None and not self._client.is_closed:
            self._client.headers[HEADER_AUTHORIZATION] = self._headers[HEADER_AUTHORIZATION]

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
        retry: bool | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated synchronous HTTP request.

        Args:
            method: The HTTP verb to use (e.g. ``GET``, ``POST``).
            path: The endpoint path appended to the base API URL.
            params: Optional query parameters.
            json_body: Optional JSON payload to send as the request body.
            data: Optional form-encoded data to send as the request body.
            content: Optional raw request body (e.g. signed orders).
            headers: Optional extra headers merged into the request.
            retry: Retry on timeout with backoff. Defaults to True for GET and False for
                every other verb: a timed-out POST/PUT/DELETE may already have been
                processed (an order, an OTP), so replaying it is not safe.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        url = _route(self._config, path)
        replayable = _should_retry(method, retry)
        logger.debug("[%s] %s", method, path)

        def _do_request() -> dict[str, Any]:
            client = self._get_client()
            response = client.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                content=content,
                headers=headers,
            )
            self.rate_limit = _observe_rate_limit(self._rate_limiter, response)
            return _handle_response(response)

        attempt = 0
        while True:
            self._rate_limiter.acquire()
            try:
                if not replayable:
                    return _do_request()
                return retry_sync(
                    _do_request,
                    max_retries=self._config.max_retries,
                    delay=self._config.retry_delay,
                )
            except RateLimitError as exc:
                wait = _rate_wait(exc, attempt)
                if not replayable or wait is None or attempt >= RATE_LIMIT_MAX_RETRIES:
                    raise
                logger.info("429 on %s: waiting %.1fs (attempt %d)", path, wait, attempt + 1)
                self._rate_limiter.pause(wait)
                attempt += 1

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a GET request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a POST request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a PUT request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a DELETE request.

        Args:
            path: The endpoint path appended to the base API URL.
            **kwargs: Additional arguments forwarded to ``request``.
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        """Close the underlying HTTP client and release its connections."""
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None
