"""Token management service (Auth & OTP) — async and sync."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    EP_ACCESS_TOKEN,
    EP_REFRESH_TOKEN,
    EP_REQUEST_OTP,
    REFRESH_REAUTH_CODES,
    SMART_OTP_PENDING_CODE,
    TOKEN_EXPIRY_SKEW_SECONDS,
)
from ssi_sdk.exceptions import (
    APIError,
    AuthenticationError,
    ReauthenticationRequired,
    SmartOTPPendingError,
)
from ssi_sdk.models import OTPRequest, OTPResponse, RefreshTokenRequest, Token, TokenRequest
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.utils.redact import redact

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
    if isinstance(error, SmartOTPPendingError):
        return True
    body = error.response_body
    return isinstance(body, dict) and str(body.get("code")) == str(SMART_OTP_PENDING_CODE)


def _is_reauth_error(error: AuthenticationError | APIError) -> bool:
    """Whether a refresh failure means the refresh token is dead (401101 / 401103).

    The server treats a reused refresh token as a leak and revokes the apiKey's whole
    session, so the only way forward is a new OTP login — never retry.
    """
    return str(error.code) in {str(code) for code in REFRESH_REAUTH_CODES}


def _poll_attempts(config: Config, interval: float | None, max_retries: int | None) -> tuple:
    """Resolve Smart OTP poll (interval, attempts); explicit args win over ``config``."""
    wait = config.otp_poll_interval if interval is None else interval
    if max_retries is not None:
        return wait, max(1, max_retries)
    if wait <= 0:
        return wait, 1
    return wait, max(1, math.ceil(config.otp_poll_max_wait / wait))


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
        raise APIError(f"Unexpected response format while {context}", response_body=redact(data))
    payload = data.get("data", data)
    if not isinstance(payload, dict):
        raise APIError(
            f"Unexpected token payload format while {context}", response_body=redact(data)
        )
    token = Token.from_dict(payload)
    if not token.access_token:
        raise APIError(
            f"{context.capitalize()} payload is missing access token", response_body=redact(data)
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
        """Whether the current access token is missing or (nearly) expired.

        A 30-second skew is applied so a token is never sent seconds before it dies; a
        token with an unknown expiry (<= 0) is treated as expired.

        Returns:
            True if no token is set or it is expired/expiring, otherwise False.
        """
        if self._token is None:
            return True
        if self._token.expires_at <= 0:
            return True
        return time.time() >= self._token.expires_at - TOKEN_EXPIRY_SKEW_SECONDS

    @property
    def has_refresh_token(self) -> bool:
        """Whether a refresh token is available.

        Returns:
            True if the current token carries a refresh token, otherwise False.
        """
        return bool(self._token and self._token.refresh_token)

    @property
    def can_refresh(self) -> bool:
        """Whether the current token can still be refreshed (refresh token not expired).

        Returns:
            True if a refresh token is present and has not expired.
        """
        return bool(self._token and self._token.can_refresh)

    def _check_refreshable(self) -> None:
        """Raise unless a refresh can be attempted.

        Raises:
            AuthenticationError: If there is no refresh token at all.
            ReauthenticationRequired: If the refresh token has expired (new OTP needed).
        """
        if not self.has_refresh_token:
            raise AuthenticationError("No refresh token available — authenticate first")
        if not self.can_refresh:
            raise ReauthenticationRequired(
                "Refresh token expired — authenticate again with a new OTP"
            )

    def _clear_token(self) -> None:
        """Forget the token and stop sending it; the session is unusable."""
        self._token = None
        self._rest.clear_auth_header()

    def _coalesced(self, observed_access_token: str | None) -> bool:
        """Whether another caller already refreshed while this one waited for the lock."""
        return (
            self._token is not None
            and self._token.access_token != observed_access_token
            and not self.is_token_expired
        )


# ── async class ──────────────────────────────────────────────


class AsyncTokenManager(_TokenState):
    """Async token manager — authentication tokens and OTP verification."""

    def __init__(self, rest_client: AsyncRestClient, config: Config):
        """Initialize the async token manager with a REST client and config."""
        super().__init__()
        self._rest = rest_client
        self._config = config
        self._refresh_lock = asyncio.Lock()

    async def refresh(self) -> Token:
        """Obtain a new access token using the current refresh token.

        Concurrent callers are coalesced: only one request reaches the server, the others
        reuse its result. Note the lock is per process — the server keeps one active session
        per apiKey, so a login/refresh in another process invalidates this token.

        Returns:
            The newly refreshed token.
        Raises:
            AuthenticationError: If no refresh token is available.
            ReauthenticationRequired: If the refresh token expired or the server rejected it
                (401101/401103); the stored token is cleared and a new OTP is required.
            APIError: If the request fails or the response is invalid.
        """
        return await self._refresh(force=True)

    async def _refresh(self, force: bool) -> Token:
        """Refresh under the single-flight lock.

        Args:
            force: When False (the ``ensure_authenticated`` path) the refresh is skipped if
                another caller already renewed the token while this one waited for the lock.
                When True it is skipped only if the token changed while waiting.
        """
        self._check_refreshable()
        observed = self.access_token
        async with self._refresh_lock:
            if self._coalesced(observed) or (not force and not self.is_token_expired):
                return self._token  # type: ignore[return-value]
            self._check_refreshable()
            body = _build_refresh_request(self._config, self._token.refresh_token)
            try:
                data = await self._rest.post(EP_REFRESH_TOKEN, json_body=body, retry=False)
            except (AuthenticationError, APIError) as exc:
                if _is_reauth_error(exc):
                    self._clear_token()
                    raise ReauthenticationRequired(
                        "Refresh token rejected by the server — authenticate again with a new OTP",
                        code=exc.code,
                        status_code=exc.status_code,
                        response_body=exc.response_body,
                    ) from exc
                raise
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
                transaction_id are given, or (for Smart OTP) approval is pending/rejected.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_auth_request(self._config, otp, transaction_id)
        data = await self._rest.post(EP_ACCESS_TOKEN, json_body=body, retry=False)
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
            The raw OTP request response. Use ``request_otp_typed`` for a model.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_otp_request(self._config)
        data = await self._rest.post(EP_REQUEST_OTP, json_body=body, retry=False)
        if not isinstance(data, dict):
            raise APIError("Unexpected response format while requesting OTP")
        return data

    async def request_otp_typed(self) -> OTPResponse:
        """Request an OTP and return it as an :class:`OTPResponse`.

        Returns:
            The parsed response; ``transaction_id`` is set only for Smart OTP.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        return OTPResponse.from_dict(await self.request_otp())

    async def ensure_authenticated(
        self,
        otp: str | None = None,
        transaction_id: str | None = None,
        poll_interval: float | None = None,
        poll_max_retries: int | None = None,
    ) -> str:
        """Ensure a valid token is available, refreshing or authenticating as needed.

        A still-valid token is returned as is. Otherwise: refresh if the refresh token is
        usable, else log in with ``otp`` / ``transaction_id``.

        Args:
            otp: Normal OTP code typed by the user — verified in a single call.
            transaction_id: Smart OTP transaction id (from ``request_otp``).
                Since approval on the device is asynchronous, this polls
                ``authenticate`` every ``poll_interval`` seconds until the user approves.
                If polling runs out while the transaction is still valid, call again
                with the same ``transaction_id``.
            poll_interval: Seconds between Smart OTP polls (default ``Config.otp_poll_interval``).
            poll_max_retries: Max Smart OTP poll attempts (default: ``Config.otp_poll_max_wait``
                divided by the interval).
        Returns:
            The current valid access token.
        Raises:
            ReauthenticationRequired: The session cannot be refreshed and no OTP was given.
            AuthenticationError: No token and no OTP/transaction id, or Smart OTP approval
                was not confirmed in time (``SmartOTPPendingError``) or was rejected
                (``SmartOTPRejectedError``).
            APIError: If a refresh or authentication request fails for another reason.
        """
        if self._token is not None and not self.is_token_expired:
            return self._token.access_token
        if self._token is not None and self.can_refresh:
            await self._refresh(force=False)
        elif otp:
            await self.authenticate(otp=otp)
        elif transaction_id:
            await self._poll_smart_otp(transaction_id, poll_interval, poll_max_retries)
        elif self._token is not None:
            raise ReauthenticationRequired(
                "Session expired and cannot be refreshed — authenticate again with a new OTP"
            )
        else:
            raise AuthenticationError(
                "OTP or Smart OTP transaction_id is required to authenticate — "
                "no token available"
            )
        return self._token.access_token

    async def _poll_smart_otp(
        self, transaction_id: str, interval: float | None, max_retries: int | None
    ) -> Token:
        """Poll authenticate() with a Smart OTP transaction id until approved or polls run out.

        A pending approval (202/401114) keeps polling; any other error — including the
        rejected/expired/unknown-transaction codes — stops immediately.
        """
        wait, attempts = _poll_attempts(self._config, interval, max_retries)
        for attempt in range(1, attempts + 1):
            try:
                return await self.authenticate(transaction_id=transaction_id)
            except (AuthenticationError, APIError) as exc:
                if not _is_smart_otp_pending(exc):
                    raise
                if attempt >= attempts:
                    raise SmartOTPPendingError(
                        f"Smart OTP approval not confirmed after {attempts} "
                        "attempts — ask the user to approve the request on their device, "
                        "then call again with the same transaction_id",
                        code=exc.code,
                        status_code=exc.status_code,
                    ) from exc
                logger.info(
                    "Smart OTP approval still pending (attempt %d/%d), retrying in %.0fs...",
                    attempt,
                    attempts,
                    wait,
                )
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover


# ── sync class ───────────────────────────────────────────────


class TokenManager(_TokenState):
    """Synchronous token manager — authentication tokens and OTP verification."""

    def __init__(self, rest_client: RestClient, config: Config):
        """Initialize the sync token manager with a REST client and config."""
        super().__init__()
        self._rest = rest_client
        self._config = config
        self._refresh_lock = threading.Lock()

    def refresh(self) -> Token:
        """Obtain a new access token using the current refresh token.

        Concurrent callers are coalesced: only one request reaches the server, the others
        reuse its result. Note the lock is per process — the server keeps one active session
        per apiKey, so a login/refresh in another process invalidates this token.

        Returns:
            The newly refreshed token.
        Raises:
            AuthenticationError: If no refresh token is available.
            ReauthenticationRequired: If the refresh token expired or the server rejected it
                (401101/401103); the stored token is cleared and a new OTP is required.
            APIError: If the request fails or the response is invalid.
        """
        return self._refresh(force=True)

    def _refresh(self, force: bool) -> Token:
        """Refresh under the single-flight lock.

        Args:
            force: When False (the ``ensure_authenticated`` path) the refresh is skipped if
                another caller already renewed the token while this one waited for the lock.
                When True it is skipped only if the token changed while waiting.
        """
        self._check_refreshable()
        observed = self.access_token
        with self._refresh_lock:
            if self._coalesced(observed) or (not force and not self.is_token_expired):
                return self._token  # type: ignore[return-value]
            self._check_refreshable()
            body = _build_refresh_request(self._config, self._token.refresh_token)
            try:
                data = self._rest.post(EP_REFRESH_TOKEN, json_body=body, retry=False)
            except (AuthenticationError, APIError) as exc:
                if _is_reauth_error(exc):
                    self._clear_token()
                    raise ReauthenticationRequired(
                        "Refresh token rejected by the server — authenticate again with a new OTP",
                        code=exc.code,
                        status_code=exc.status_code,
                        response_body=exc.response_body,
                    ) from exc
                raise
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
                transaction_id are given, or (for Smart OTP) approval is pending/rejected.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_auth_request(self._config, otp, transaction_id)
        data = self._rest.post(EP_ACCESS_TOKEN, json_body=body, retry=False)
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
            The raw OTP request response. Use ``request_otp_typed`` for a model.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        body = _build_otp_request(self._config)
        data = self._rest.post(EP_REQUEST_OTP, json_body=body, retry=False)
        if not isinstance(data, dict):
            raise APIError("Unexpected response format while requesting OTP")
        return data

    def request_otp_typed(self) -> OTPResponse:
        """Request an OTP and return it as an :class:`OTPResponse`.

        Returns:
            The parsed response; ``transaction_id`` is set only for Smart OTP.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        return OTPResponse.from_dict(self.request_otp())

    def ensure_authenticated(
        self,
        otp: str | None = None,
        transaction_id: str | None = None,
        poll_interval: float | None = None,
        poll_max_retries: int | None = None,
    ) -> str:
        """Ensure a valid token is available, refreshing or authenticating as needed.

        A still-valid token is returned as is. Otherwise: refresh if the refresh token is
        usable, else log in with ``otp`` / ``transaction_id``.

        Args:
            otp: Normal OTP code typed by the user — verified in a single call.
            transaction_id: Smart OTP transaction id (from ``request_otp``).
                Since approval on the device is asynchronous, this polls
                ``authenticate`` every ``poll_interval`` seconds until the user approves.
                If polling runs out while the transaction is still valid, call again
                with the same ``transaction_id``.
            poll_interval: Seconds between Smart OTP polls (default ``Config.otp_poll_interval``).
            poll_max_retries: Max Smart OTP poll attempts (default: ``Config.otp_poll_max_wait``
                divided by the interval).
        Returns:
            The current valid access token.
        Raises:
            ReauthenticationRequired: The session cannot be refreshed and no OTP was given.
            AuthenticationError: No token and no OTP/transaction id, or Smart OTP approval
                was not confirmed in time (``SmartOTPPendingError``) or was rejected
                (``SmartOTPRejectedError``).
            APIError: If a refresh or authentication request fails for another reason.
        """
        if self._token is not None and not self.is_token_expired:
            return self._token.access_token
        if self._token is not None and self.can_refresh:
            self._refresh(force=False)
        elif otp:
            self.authenticate(otp=otp)
        elif transaction_id:
            self._poll_smart_otp(transaction_id, poll_interval, poll_max_retries)
        elif self._token is not None:
            raise ReauthenticationRequired(
                "Session expired and cannot be refreshed — authenticate again with a new OTP"
            )
        else:
            raise AuthenticationError(
                "OTP or Smart OTP transaction_id is required to authenticate — "
                "no token available"
            )
        return self._token.access_token

    def _poll_smart_otp(
        self, transaction_id: str, interval: float | None, max_retries: int | None
    ) -> Token:
        """Poll authenticate() with a Smart OTP transaction id until approved or polls run out.

        A pending approval (202/401114) keeps polling; any other error — including the
        rejected/expired/unknown-transaction codes — stops immediately.
        """
        wait, attempts = _poll_attempts(self._config, interval, max_retries)
        for attempt in range(1, attempts + 1):
            try:
                return self.authenticate(transaction_id=transaction_id)
            except (AuthenticationError, APIError) as exc:
                if not _is_smart_otp_pending(exc):
                    raise
                if attempt >= attempts:
                    raise SmartOTPPendingError(
                        f"Smart OTP approval not confirmed after {attempts} "
                        "attempts — ask the user to approve the request on their device, "
                        "then call again with the same transaction_id",
                        code=exc.code,
                        status_code=exc.status_code,
                    ) from exc
                logger.info(
                    "Smart OTP approval still pending (attempt %d/%d), retrying in %.0fs...",
                    attempt,
                    attempts,
                    wait,
                )
                time.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover
