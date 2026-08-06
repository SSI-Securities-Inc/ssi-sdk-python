"""Token management service (Auth & OTP) — async and sync."""

from __future__ import annotations

import asyncio
import logging
import time

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    EP_ACCESS_TOKEN,
    EP_REFRESH_TOKEN,
    EP_REQUEST_OTP,
    SMART_OTP_PENDING_CODE,
    SMART_OTP_PENDING_STATUS,
    SMART_OTP_POLL_INTERVAL,
    SMART_OTP_POLL_MAX_RETRIES,
)
from ssi_sdk.exceptions import APIError, AuthenticationError
from ssi_sdk.models import OTPRequest, RefreshTokenRequest, Token, TokenRequest
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient

logger = logging.getLogger("ssi_sdk.services.token_manager")


# ── shared logic ─────────────────────────────────────────────


def _build_auth_request(
    config: Config, otp: str | None = None, transaction_id: str | None = None
) -> dict:
    """Build the authentication request body from config credentials and OTP.

    Args:
        config: SDK config carrying ``api_key``/``api_secret``.
        otp: Normal OTP code typed by the user (SMS/email).
        transaction_id: Smart OTP transaction id, once the user approves it
            on their device. Mutually exclusive with ``otp``.
    """
    if not config.api_key or not config.api_secret:
        raise AuthenticationError(
            "api_key and api_secret are required for authentication"
        )
    if otp and transaction_id:
        raise AuthenticationError("Pass only one of otp or transaction_id, not both")
    return TokenRequest(
        api_key=config.api_key,
        api_secret=config.api_secret,
        otp=otp,
        transaction_id=transaction_id,
    ).to_dict()


def _is_smart_otp_pending(error: AuthenticationError | APIError) -> bool:
    """Whether an auth error means the Smart OTP approval is still pending.

    Confirmed against SSI FastConnect: HTTP 202 with body
    ``{"code": 401114, "msg": "Push-approval is pending"}``.
    """
    body = error.response_body
    if isinstance(body, dict) and (body.get("code") == SMART_OTP_PENDING_CODE or body.get("code") == 401114 or body.get("status") == 202):
        return True
    return error.status_code == SMART_OTP_PENDING_STATUS or error.status_code == 202


def _build_refresh_request(config: Config, refresh_token: str) -> dict:
    """Build the token refresh request body from the given refresh token."""
    if not config.api_key or not config.api_secret:
        raise AuthenticationError(
            "api_key and api_secret are required for token refresh"
        )
    return RefreshTokenRequest(refresh_token=refresh_token).to_dict()


def _build_otp_request(config: Config) -> dict:
    """Build the OTP request body from config credentials."""
    if not config.api_key or not config.api_secret:
        raise AuthenticationError("api_key and api_secret are required for OTP request")
    return OTPRequest(
        api_key=config.api_key,
        api_secret=config.api_secret,
    ).to_dict()


def _parse_token(data, context: str) -> Token:
    """Parse and validate a token from a raw response payload."""
    if not isinstance(data, dict):
        raise APIError(f"Unexpected response format while {context}", status_code=SMART_OTP_PENDING_STATUS, response_body=data)
    payload = data.get("data", data)
    if not isinstance(payload, dict):
        raise APIError(f"Unexpected token payload format while {context}", status_code=SMART_OTP_PENDING_STATUS, response_body=data)
    token = Token.from_dict(payload)
    if not token.access_token:
        raise APIError(
            f"{context.capitalize()} payload is missing access token",
            status_code=SMART_OTP_PENDING_STATUS,
            response_body=data,
        )
    return token


class _TokenState:
    """Shared token state properties — no I/O."""

    def __init__(self) -> None:
        """Initialize the token state with no token set."""
        self._token: Token | None = None

    @property
    def token(self) -> Token | None:
        """The current token.

        Returns:
            The current token, or None if no token is set.
        """
        return self._token

    @property
    def access_token(self) -> str | None:
        """The current access token string.

        Returns:
            The current access token, or None if no token is set.
        """
        if self._token is None:
            return None
        return self._token.access_token

    @property
    def is_token_expired(self) -> bool:
        """Whether the current token is missing or expired.

        Returns:
            True if no token is set or the token has expired, otherwise False.
        """
        if self._token is None:
            return True
        if self._token.expires_at <= 0:
            return False
        return time.time() >= self._token.expires_at

    @property
    def has_refresh_token(self) -> bool:
        """Whether a refresh token is available.

        Returns:
            True if the current token carries a refresh token, otherwise False.
        """
        return bool(self._token and self._token.refresh_token)


# ── async class ──────────────────────────────────────────────


class AsyncTokenManager(_TokenState):
    """Async token manager — authentication tokens and OTP verification."""

    def __init__(self, rest_client: AsyncRestClient, config: Config):
        """Initialize the async token manager with a REST client and config."""
        super().__init__()
        self._rest = rest_client
        self._config = config

    async def refresh(self) -> Token:
        """Obtain a new access token using the current refresh token.

        Returns:
            The newly refreshed token.
        Raises:
            AuthenticationError: If no refresh token is available.
            APIError: If the request fails or the response is invalid.
        """
        if not self.has_refresh_token:
            raise AuthenticationError("No refresh token available — authenticate first")
        body = _build_refresh_request(self._config, self._token.refresh_token)
        data = await self._rest.post(EP_REFRESH_TOKEN, json_body=body)
        self._token = _parse_token(data, "refreshing")
        self._rest.set_auth_header(self._token.access_token)
        logger.info("Token refreshed successfully")
        return self._token

    async def authenticate(
        self, otp: str | None = None, transaction_id: str | None = None
    ) -> Token:
        """Authenticate using consumer credentials and OTP to obtain an access token.

        Args:
            otp: Normal OTP code typed by the user (SMS/email).
            transaction_id: Smart OTP transaction id (from ``request_otp``),
                used once the user approves the request on their device.
                Mutually exclusive with ``otp``.
        Returns:
            The newly issued token.
        Raises:
            AuthenticationError: If the API key or secret is missing, both otp and
                transaction_id are given, or (for Smart OTP) approval is still pending.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_auth_request(self._config, otp, transaction_id)
        data = await self._rest.post(EP_ACCESS_TOKEN, json_body=body)
        self._token = _parse_token(data, "authenticating")
        self._rest.set_auth_header(self._token.access_token)
        logger.info("Authentication successful")
        return self._token

    async def set_token(self, token: Token) -> None:
        """Manually set the access token (for advanced use cases).

        Args:
            token: The token to set as the current token.
        """
        self._token = token
        self._rest.set_auth_header(token.access_token)
        logger.info("Access token set manually")

    async def request_otp(self) -> dict:
        """Request an OTP to be sent (normal OTP) or pushed for approval (Smart OTP).

        Both account types share the same request endpoint — the server
        decides how to deliver the OTP based on how the account was
        registered (SMS/email vs Smart OTP push-approval).

        Returns:
            The raw OTP request response.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_otp_request(self._config)
        data = await self._rest.post(EP_REQUEST_OTP, json_body=body)
        if not isinstance(data, dict):
            raise APIError("Unexpected response format while requesting OTP")
        return data

    async def ensure_authenticated(
        self,
        otp: str | None = None,
        transaction_id: str | None = None,
        poll_interval: float = SMART_OTP_POLL_INTERVAL,
        poll_max_retries: int = SMART_OTP_POLL_MAX_RETRIES,
    ) -> str:
        """Ensure a valid token is available, refreshing or authenticating as needed.

        Args:
            otp: Normal OTP code typed by the user — verified in a single call.
            transaction_id: Smart OTP transaction id (from ``request_otp``).
                Since approval on the device is asynchronous, this polls
                ``authenticate`` every ``poll_interval`` seconds, up to
                ``poll_max_retries`` attempts, until the user approves.
            poll_interval: Seconds to wait between Smart OTP approval polls.
            poll_max_retries: Max number of Smart OTP approval poll attempts.
        Returns:
            The current valid access token.
        Raises:
            AuthenticationError: If no valid token can be obtained, or Smart OTP
                approval is not confirmed within ``poll_max_retries`` attempts.
            APIError: If a refresh or authentication request fails for a reason
                other than pending Smart OTP approval.
        """
        if self._token is None or self.is_token_expired:
            if self.has_refresh_token:
                await self.refresh()
            elif otp:
                await self.authenticate(otp=otp)
            elif transaction_id:
                await self._poll_smart_otp(
                    transaction_id, poll_interval, poll_max_retries
                )
            else:
                raise AuthenticationError(
                    "OTP or Smart OTP transaction_id is required to authenticate — "
                    "no refresh token available"
                )
        return self._token.access_token

    async def _poll_smart_otp(
        self, transaction_id: str, interval: float, max_retries: int
    ) -> Token:
        """Poll authenticate() with a Smart OTP transaction id until approved or retries exhausted."""
        for attempt in range(1, max_retries + 1):
            try:
                return await self.authenticate(transaction_id=transaction_id)
            except (AuthenticationError, APIError) as exc:
                if not _is_smart_otp_pending(exc):
                    raise
                if attempt >= max_retries:
                    raise AuthenticationError(
                        f"Smart OTP approval not confirmed after {max_retries} "
                        "attempts — ask the user to approve the request on "
                        "their device"
                    ) from exc
                logger.info(
                    "Smart OTP approval still pending (attempt %d/%d), "
                    "retrying in %.0fs...",
                    attempt,
                    max_retries,
                    interval,
                )
                await asyncio.sleep(interval)


# ── sync class ───────────────────────────────────────────────


class TokenManager(_TokenState):
    """Synchronous token manager — authentication tokens and OTP verification."""

    def __init__(self, rest_client: RestClient, config: Config):
        """Initialize the sync token manager with a REST client and config."""
        super().__init__()
        self._rest = rest_client
        self._config = config

    def refresh(self) -> Token:
        """Obtain a new access token using the current refresh token.

        Returns:
            The newly refreshed token.
        Raises:
            AuthenticationError: If no refresh token is available.
            APIError: If the request fails or the response is invalid.
        """
        if not self.has_refresh_token:
            raise AuthenticationError("No refresh token available — authenticate first")
        body = _build_refresh_request(self._config, self._token.refresh_token)
        data = self._rest.post(EP_REFRESH_TOKEN, json_body=body)
        self._token = _parse_token(data, "refreshing")
        self._rest.set_auth_header(self._token.access_token)
        logger.info("Token refreshed successfully")
        return self._token

    def authenticate(
        self, otp: str | None = None, transaction_id: str | None = None
    ) -> Token:
        """Authenticate using consumer credentials and OTP to obtain an access token.

        Args:
            otp: Normal OTP code typed by the user (SMS/email).
            transaction_id: Smart OTP transaction id (from ``request_otp``),
                used once the user approves the request on their device.
                Mutually exclusive with ``otp``.
        Returns:
            The newly issued token.
        Raises:
            AuthenticationError: If the API key or secret is missing, both otp and
                transaction_id are given, or (for Smart OTP) approval is still pending.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_auth_request(self._config, otp, transaction_id)
        data = self._rest.post(EP_ACCESS_TOKEN, json_body=body)
        self._token = _parse_token(data, "authenticating")
        self._rest.set_auth_header(self._token.access_token)
        logger.info("Authentication successful")
        return self._token

    def set_token(self, token: Token) -> None:
        """Manually set the access token (for advanced use cases).

        Args:
            token: The token to set as the current token.
        """
        self._token = token
        self._rest.set_auth_header(token.access_token)
        logger.info("Access token set manually")

    def request_otp(self) -> dict:
        """Request an OTP to be sent (normal OTP) or pushed for approval (Smart OTP).

        Both account types share the same request endpoint — the server
        decides how to deliver the OTP based on how the account was
        registered (SMS/email vs Smart OTP push-approval).

        Returns:
            The raw OTP request response.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_otp_request(self._config)
        data = self._rest.post(EP_REQUEST_OTP, json_body=body)
        if not isinstance(data, dict):
            raise APIError("Unexpected response format while requesting OTP")
        return data

    def ensure_authenticated(
        self,
        otp: str | None = None,
        transaction_id: str | None = None,
        poll_interval: float = SMART_OTP_POLL_INTERVAL,
        poll_max_retries: int = SMART_OTP_POLL_MAX_RETRIES,
    ) -> str:
        """Ensure a valid token is available, refreshing or authenticating as needed.

        Args:
            otp: Normal OTP code typed by the user — verified in a single call.
            transaction_id: Smart OTP transaction id (from ``request_otp``).
                Since approval on the device is asynchronous, this polls
                ``authenticate`` every ``poll_interval`` seconds, up to
                ``poll_max_retries`` attempts, until the user approves.
            poll_interval: Seconds to wait between Smart OTP approval polls.
            poll_max_retries: Max number of Smart OTP approval poll attempts.
        Returns:
            The current valid access token.
        Raises:
            AuthenticationError: If no valid token can be obtained, or Smart OTP
                approval is not confirmed within ``poll_max_retries`` attempts.
            APIError: If a refresh or authentication request fails for a reason
                other than pending Smart OTP approval.
        """
        if self._token is None or self.is_token_expired:
            if self.has_refresh_token:
                self.refresh()
            elif otp:
                self.authenticate(otp=otp)
            elif transaction_id:
                self._poll_smart_otp(transaction_id, poll_interval, poll_max_retries)
            else:
                raise AuthenticationError(
                    "OTP or Smart OTP transaction_id is required to authenticate — "
                    "no refresh token available"
                )
        return self._token.access_token

    def _poll_smart_otp(
        self, transaction_id: str, interval: float, max_retries: int
    ) -> Token:
        """Poll authenticate() with a Smart OTP transaction id until approved or retries exhausted."""
        for attempt in range(1, max_retries + 1):
            try:
                return self.authenticate(transaction_id=transaction_id)
            except (AuthenticationError, APIError) as exc:
                if not _is_smart_otp_pending(exc):
                    raise
                if attempt >= max_retries:
                    raise AuthenticationError(
                        f"Smart OTP approval not confirmed after {max_retries} "
                        "attempts — ask the user to approve the request on "
                        "their device"
                    ) from exc
                logger.info(
                    "Smart OTP approval still pending (attempt %d/%d), "
                    "retrying in %.0fs...",
                    attempt,
                    max_retries,
                    interval,
                )
                time.sleep(interval)
