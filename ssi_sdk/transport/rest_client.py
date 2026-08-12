"""REST client for SSI API (async and sync)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    AUTH_SCHEME_BEARER,
    CONTENT_TYPE_JSON,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    HEADER_CONTENT_TYPE,
    HEADER_RETRY_AFTER,
    HEADER_USER_AGENT,
    DEFAULT_USER_AGENT,
)
from ssi_sdk.enums import HTTPStatus
from ssi_sdk.exceptions import APIError, AuthenticationError, RateLimitError
from ssi_sdk.utils.retry import RateLimiter, retry_async, retry_sync

logger = logging.getLogger("ssi_sdk.transport.rest")


def _handle_response(response: httpx.Response) -> dict[str, Any]:
    """Parse and validate an HTTP response."""
    logger.debug("Received response: %s %s", response.status_code, response.text)
    if response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        body = None
        try:
            body = response.json()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        raise AuthenticationError(
            f"Authentication failed: {response.status_code}",
            code=str(response.status_code),
            status_code=response.status_code,
            response_body=body,
        )

    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        retry_after = response.headers.get(HEADER_RETRY_AFTER)
        raise RateLimitError(
            "Rate limit exceeded",
            retry_after=float(retry_after) if retry_after else None,
        )

    if response.status_code >= HTTPStatus.BAD_REQUEST:
        body = None
        try:
            body = response.json()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        raise APIError(
            message=f"API error: {response.status_code}",
            code=str(response.status_code),
            status_code=response.status_code,
            response_body=body,
        )

    if response.status_code == HTTPStatus.NO_CONTENT:
        return {}

    return response.json()


class AsyncRestClient:
    """Async HTTP client for SSI REST API."""

    def __init__(self, config: Config):
        """Initialize the async REST client with the given configuration."""
        self._config = config
        self._rate_limiter = RateLimiter(config.rate_limit_per_second)
        self._client: httpx.AsyncClient | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
            HEADER_USER_AGENT: DEFAULT_USER_AGENT,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the cached HTTP client, lazily creating it if needed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._config.api_url,
                timeout=self._config.timeout,
                headers=self._headers,
                proxy=self._config.proxy,
            )
        return self._client

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
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        await self._rate_limiter.async_acquire()

        async def _do_request() -> dict[str, Any]:
            client = await self._get_client()
            response = await client.request(
                method,
                path,
                params=params,
                json=json_body,
                data=data,
                content=content,
                headers=headers,
            )
            return _handle_response(response)

        return await retry_async(
            _do_request,
            max_retries=self._config.max_retries,
            delay=self._config.retry_delay,
        )

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

    def __init__(self, config: Config):
        """Initialize the sync REST client with the given configuration."""
        self._config = config
        self._rate_limiter = RateLimiter(config.rate_limit_per_second)
        self._client: httpx.Client | None = None
        self._headers: dict = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
            HEADER_USER_AGENT: DEFAULT_USER_AGENT,
        }

    def _get_client(self) -> httpx.Client:
        """Return the cached HTTP client, lazily creating it if needed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self._config.api_url,
                timeout=self._config.timeout,
                headers=self._headers,
                proxy=self._config.proxy,
            )
        return self._client

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
        Returns:
            The parsed JSON response body as a dict.
        Raises:
            AuthenticationError: If the response status is 401 or 403.
            RateLimitError: If the response status is 429.
            APIError: If the response status is any other 4xx/5xx error.
        """
        self._rate_limiter.acquire()
        logger.debug(
            "[%s] %s with params=%s, data=%s, json=%s, content=%s, headers=%s",
            method,
            path,
            params,
            data,
            json_body,
            content,
            headers,
        )

        def _do_request() -> dict[str, Any]:
            client = self._get_client()
            response = client.request(
                method,
                path,
                params=params,
                json=json_body,
                data=data,
                content=content,
                headers=headers,
            )
            return _handle_response(response)

        return retry_sync(
            _do_request,
            max_retries=self._config.max_retries,
            delay=self._config.retry_delay,
        )

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
