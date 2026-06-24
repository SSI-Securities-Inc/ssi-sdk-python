"""Token management service (Auth & OTP) — async and sync."""

from __future__ import annotations

import logging
import time

from ssi_sdk.config import Config
from ssi_sdk.constant import EP_ACCESS_TOKEN, EP_REFRESH_TOKEN, EP_REQUEST_OTP
from ssi_sdk.exceptions import APIError, AuthenticationError
from ssi_sdk.models import OTPRequest, RefreshTokenRequest, Token, TokenRequest
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient

logger = logging.getLogger("ssi_sdk.services.token_manager")


# ── shared logic ─────────────────────────────────────────────


def _build_auth_request(config: Config, otp: str | None = None) -> dict:
    """Build the authentication request body from config credentials and optional OTP."""
    if not config.api_key or not config.api_secret:
        raise AuthenticationError("api_key and api_secret are required for authentication")
    return TokenRequest(
        api_key=config.api_key,
        api_secret=config.api_secret,
        otp=otp,
    ).to_dict()


def _build_refresh_request(config: Config, refresh_token: str) -> dict:
    """Build the token refresh request body from the given refresh token."""
    if not config.api_key or not config.api_secret:
        raise AuthenticationError("api_key and api_secret are required for token refresh")
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
        raise APIError(f"Unexpected response format while {context}")
    payload = data.get("data", data)
    if not isinstance(payload, dict):
        raise APIError(f"Unexpected token payload format while {context}")
    token = Token.from_dict(payload)
    if not token.access_token:
        raise APIError(f"{context.capitalize()} payload is missing access token")
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

    async def authenticate(self, otp: str | None = None) -> Token:
        """Authenticate using consumer credentials and OTP to obtain an access token.

        Args:
            otp: The one-time password used to authenticate.
        Returns:
            The newly issued token.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_auth_request(self._config, otp)
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
        """Request an OTP to be sent to the registered channel.

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

    async def ensure_authenticated(self, otp: str | None = None) -> str:
        """Ensure a valid token is available, refreshing or authenticating as needed.

        Args:
            otp: The one-time password used if authentication is required.
        Returns:
            The current valid access token.
        Raises:
            AuthenticationError: If no valid token can be obtained.
            APIError: If a refresh or authentication request fails.
        """
        if self._token is None or self.is_token_expired:
            if self.has_refresh_token:
                await self.refresh()
            elif otp:
                await self.authenticate(otp)
            else:
                raise AuthenticationError(
                    "OTP is required to authenticate — no refresh token available"
                )
        return self._token.access_token


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

    def authenticate(self, otp: str | None = None) -> Token:
        """Authenticate using consumer credentials and OTP to obtain an access token.

        Args:
            otp: The one-time password used to authenticate.
        Returns:
            The newly issued token.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_auth_request(self._config, otp)
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
        """Request an OTP to be sent to the registered channel.

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

    def ensure_authenticated(self, otp: str | None = None) -> str:
        """Ensure a valid token is available, refreshing or authenticating as needed.

        Args:
            otp: The one-time password used if authentication is required.
        Returns:
            The current valid access token.
        Raises:
            AuthenticationError: If no valid token can be obtained.
            APIError: If a refresh or authentication request fails.
        """
        if self._token is None or self.is_token_expired:
            if self.has_refresh_token:
                self.refresh()
            elif otp:
                self.authenticate(otp)
            else:
                raise AuthenticationError(
                    "OTP is required to authenticate — no refresh token available"
                )
        return self._token.access_token
