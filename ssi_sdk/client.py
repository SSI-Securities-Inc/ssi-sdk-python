"""SSI clients — unified and specialized entry points for the SDK.

Clients overview
~~~~~~~~~~~~~~~~

+---------------------+---------------------------------------------------+
| Client              | Use-case                                          |
+=====================+===================================================+
| ``Auth``      | Credentials + token management. Entry point for   |
|               | all other clients.                                |
| ``AsyncAuth`` | Async version of Auth.                            |
+---------------------+---------------------------------------------------+
| ``Data``      | Market data — pass Auth (no OTP needed).          |
| ``AsyncData`` | Async version of Data.                            |
+---------------------+---------------------------------------------------+
| ``Trading``   | Trading + portfolio + account — pass Auth after   |
|               | calling ``auth.authenticate(otp=...)``.           |
| ``AsyncTrading`` | Async version of Trading.                      |
+---------------------+---------------------------------------------------+
| ``Stream``    | Real-time WebSocket — pass Auth after             |
|               | calling ``auth.authenticate(otp=...)``.           |
| ``AsyncStream`` | Async version of Stream.                        |
+---------------------+---------------------------------------------------+
"""

from __future__ import annotations

import dataclasses
import logging

from ssi_sdk.config import Config
from ssi_sdk.models import OTPResponse, Token
from ssi_sdk.services.account import AccountService, AsyncAccountService
from ssi_sdk.services.market_data import AsyncMarketDataService, MarketDataService
from ssi_sdk.services.portfolio import AsyncPortfolioService, PortfolioService
from ssi_sdk.services.streaming import AsyncStreamingService, StreamingService
from ssi_sdk.services.token_manager import AsyncTokenManager, TokenManager
from ssi_sdk.services.trading import AsyncTradingService, TradingService
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.transport.websocket_client import AsyncWebSocketClient, WebSocketClient
from ssi_sdk.utils.logger import get_logger

logger = logging.getLogger("ssi_sdk")


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_config(config: Config | None, kwargs: dict) -> Config:
    """Build a Config, or derive one from ``config`` with ``kwargs`` applied.

    The caller's ``Config`` is never mutated: it may be shared with other clients.

    Raises:
        TypeError: If ``kwargs`` names a field that ``Config`` does not have (a typo would
            otherwise silently leave the default in place).
    """
    if config is None:
        return Config(**kwargs)  # type: ignore[arg-type]
    if not kwargs:
        return config
    unknown = sorted(set(kwargs) - {f.name for f in dataclasses.fields(Config)})
    if unknown:
        raise TypeError(f"Unknown Config option(s): {', '.join(unknown)}")
    return dataclasses.replace(config, **kwargs)  # type: ignore[arg-type]


def _expiry_of(token_manager) -> float:
    """Epoch second after which the current credentials stop working (0 if unknown)."""
    token = token_manager.token
    return token.effective_expires_at if token is not None else 0


# ═══════════════════════════════════════════════════════════════════════════
# Specialized clients — use only what you need
# ═══════════════════════════════════════════════════════════════════════════


class AsyncAuth:
    """Async client for **authentication only** — obtain and manage access tokens.

    All ``token_manager`` methods/properties are available directly on the client::

        async with AsyncAuth(api_key="...", api_secret="...") as client:
            token = await client.authenticate(otp="123456")
            await client.refresh()
            await client.request_otp()
    """

    def __init__(self, config: Config | None = None, **kwargs: object) -> None:
        """Build the Config, async REST transport, and async token manager."""
        self._config = _make_config(config, kwargs)
        get_logger(level=self._config.log_level)
        self._rest_client = AsyncRestClient(self._config)
        self.token_manager = AsyncTokenManager(self._rest_client, self._config)

    @property
    def rest_client(self) -> AsyncRestClient:
        """Shared REST client (used by Trading / Stream).

        Returns:
            The async REST client shared with Trading and Stream clients.
        """
        return self._rest_client

    @property
    def config(self) -> Config:
        """Active config.

        Returns:
            The active :class:`Config` for this client.
        """
        return self._config

    # -- token management (explicit, so IDEs can complete and show docs) -----------

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
        return await self.token_manager.authenticate(otp=otp, transaction_id=transaction_id)

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
        return await self.token_manager.refresh()

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
        return await self.token_manager.ensure_authenticated(
            otp, transaction_id, poll_interval, poll_max_retries
        )

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
        return await self.token_manager.request_otp()

    async def request_otp_typed(self) -> OTPResponse:
        """Request an OTP and return it as an :class:`OTPResponse`.

        Returns:
            The parsed response; ``transaction_id`` is set only for Smart OTP.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        return await self.token_manager.request_otp_typed()

    async def set_token(self, token: Token) -> None:
        """Manually set the access token (for advanced use cases).

        Args:
            token: The token to set as the current token.
        """
        return await self.token_manager.set_token(token)

    @property
    def token(self) -> Token | None:
        """The current token.

        Returns:
            The current token, or None if no token is set.
        """
        return self.token_manager.token

    @property
    def access_token(self) -> str | None:
        """The current access token string.

        Returns:
            The current access token, or None if no token is set.
        """
        return self.token_manager.access_token

    @property
    def is_token_expired(self) -> bool:
        """Whether the current access token is missing or (nearly) expired.

        A 30-second skew is applied so a token is never sent seconds before it dies; a
        token with an unknown expiry (<= 0) is treated as expired.

        Returns:
            True if no token is set or it is expired/expiring, otherwise False.
        """
        return self.token_manager.is_token_expired

    @property
    def has_refresh_token(self) -> bool:
        """Whether a refresh token is available.

        Returns:
            True if the current token carries a refresh token, otherwise False.
        """
        return self.token_manager.has_refresh_token

    @property
    def can_refresh(self) -> bool:
        """Whether the current token can still be refreshed (refresh token not expired).

        Returns:
            True if a refresh token is present and has not expired.
        """
        return self.token_manager.can_refresh

    def __getattr__(self, name: str) -> object:
        """Fallback: anything not defined above is looked up on ``token_manager``."""
        return getattr(self.token_manager, name)

    async def close(self) -> None:
        """Release HTTP resources held by the shared REST client.

        Returns:
            None.
        """
        await self._rest_client.close()

    async def __aenter__(self) -> AsyncAuth:
        """Enter the async context manager and return this client."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager, releasing HTTP resources."""
        await self.close()


class Auth:
    """Sync client for **authentication only** — obtain and manage access tokens.

    All ``token_manager`` methods/properties are available directly on the client::

        with Auth(api_key="...", api_secret="...") as client:
            token = client.authenticate(otp="123456")
            client.refresh()
            client.request_otp()
    """

    def __init__(self, config: Config | None = None, **kwargs: object) -> None:
        """Build the Config, sync REST transport, and sync token manager."""
        self._config = _make_config(config, kwargs)
        get_logger(level=self._config.log_level)
        self._rest_client = RestClient(self._config)
        self.token_manager = TokenManager(self._rest_client, self._config)

    @property
    def rest_client(self) -> RestClient:
        """Shared REST client (used by Trading / Stream).

        Returns:
            The sync REST client shared with Trading and Stream clients.
        """
        return self._rest_client

    @property
    def config(self) -> Config:
        """Active config.

        Returns:
            The active :class:`Config` for this client.
        """
        return self._config

    # -- token management (explicit, so IDEs can complete and show docs) -----------

    def authenticate(self, otp: str | None = None, transaction_id: str | None = None) -> Token:
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
        return self.token_manager.authenticate(otp=otp, transaction_id=transaction_id)

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
        return self.token_manager.refresh()

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
        return self.token_manager.ensure_authenticated(
            otp, transaction_id, poll_interval, poll_max_retries
        )

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
        return self.token_manager.request_otp()

    def request_otp_typed(self) -> OTPResponse:
        """Request an OTP and return it as an :class:`OTPResponse`.

        Returns:
            The parsed response; ``transaction_id`` is set only for Smart OTP.
        Raises:
            AuthenticationError: If the API key or secret is missing.
            APIError: If the request fails or the response is invalid.
        """
        return self.token_manager.request_otp_typed()

    def set_token(self, token: Token) -> None:
        """Manually set the access token (for advanced use cases).

        Args:
            token: The token to set as the current token.
        """
        return self.token_manager.set_token(token)

    @property
    def token(self) -> Token | None:
        """The current token.

        Returns:
            The current token, or None if no token is set.
        """
        return self.token_manager.token

    @property
    def access_token(self) -> str | None:
        """The current access token string.

        Returns:
            The current access token, or None if no token is set.
        """
        return self.token_manager.access_token

    @property
    def is_token_expired(self) -> bool:
        """Whether the current access token is missing or (nearly) expired.

        A 30-second skew is applied so a token is never sent seconds before it dies; a
        token with an unknown expiry (<= 0) is treated as expired.

        Returns:
            True if no token is set or it is expired/expiring, otherwise False.
        """
        return self.token_manager.is_token_expired

    @property
    def has_refresh_token(self) -> bool:
        """Whether a refresh token is available.

        Returns:
            True if the current token carries a refresh token, otherwise False.
        """
        return self.token_manager.has_refresh_token

    @property
    def can_refresh(self) -> bool:
        """Whether the current token can still be refreshed (refresh token not expired).

        Returns:
            True if a refresh token is present and has not expired.
        """
        return self.token_manager.can_refresh

    def __getattr__(self, name: str) -> object:
        """Fallback: anything not defined above is looked up on ``token_manager``."""
        return getattr(self.token_manager, name)

    def close(self) -> None:
        """Release HTTP resources held by the shared REST client.

        Returns:
            None.
        """
        self._rest_client.close()

    def __enter__(self) -> Auth:
        """Enter the context manager and return this client."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the context manager, releasing HTTP resources."""
        self.close()


class AsyncData:
    """Async client for **market data**.

    Requires ``await auth.authenticate()`` (no OTP) before use::

        async with AsyncAuth(api_key="...", api_secret="...") as auth:
            await auth.authenticate()
            async with AsyncData(auth) as client:
                ohlc = await client.market_data.get_ohlc_1minute("VNM")
    """

    def __init__(self, auth: AsyncAuth) -> None:
        """Wire the async market-data service onto the shared Auth REST client."""
        self._auth = auth
        self.market_data: AsyncMarketDataService = AsyncMarketDataService(auth.rest_client)

    async def __aenter__(self) -> AsyncData:
        """Enter the async context manager and return this client."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager; lifecycle is managed by AsyncAuth."""
        pass  # lifecycle managed by AsyncAuth


class Data:
    """Sync client for **market data**.

    Requires ``auth.authenticate()`` (no OTP) before use::

        with Auth(api_key="...", api_secret="...") as auth:
            auth.authenticate()
            with Data(auth) as client:
                ohlc = client.market_data.get_ohlc_1minute("VNM")
    """

    def __init__(self, auth: Auth) -> None:
        """Wire the sync market-data service onto the shared Auth REST client."""
        self._auth = auth
        self.market_data: MarketDataService = MarketDataService(auth.rest_client)

    def __enter__(self) -> Data:
        """Enter the context manager and return this client."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the context manager; lifecycle is managed by Auth."""
        pass  # lifecycle managed by Auth


class AsyncTrading:
    """Async client for **trading + portfolio + account**.

    Requires an already-authenticated :class:`AsyncAuth` (with OTP)::

        async with AsyncAuth(config) as auth:
            await auth.authenticate(otp="123456")
            async with AsyncTrading(auth) as client:
                order = await client.trading.place_limit_order(...)
                # also: client.account, client.portfolio
    """

    def __init__(self, auth: AsyncAuth) -> None:
        """Wire async trading, account, and portfolio services onto the shared Auth."""
        self._auth = auth
        self.token_manager = auth.token_manager
        self.trading: AsyncTradingService = AsyncTradingService(auth.rest_client)
        self.account: AsyncAccountService = AsyncAccountService(auth.rest_client)
        self.portfolio: AsyncPortfolioService = AsyncPortfolioService(auth.rest_client, auth.config)

    async def __aenter__(self) -> AsyncTrading:
        """Enter the async context manager and return this client."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager; lifecycle is managed by AsyncAuth."""
        pass  # lifecycle managed by AsyncAuth


class Trading:
    """Sync client for **trading + portfolio + account**.

    Requires an already-authenticated :class:`Auth` (with OTP)::

        with Auth(config) as auth:
            auth.authenticate(otp="123456")
            with Trading(auth) as client:
                order = client.trading.place_limit_order(...)
                # also: client.account, client.portfolio
    """

    def __init__(self, auth: Auth) -> None:
        """Wire sync trading, account, and portfolio services onto the shared Auth."""
        self._auth = auth
        self.token_manager = auth.token_manager
        self.trading: TradingService = TradingService(auth.rest_client)
        self.account: AccountService = AccountService(auth.rest_client)
        self.portfolio: PortfolioService = PortfolioService(auth.rest_client, auth.config)

    def __enter__(self) -> Trading:
        """Enter the context manager and return this client."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the context manager; lifecycle is managed by Auth."""
        pass  # lifecycle managed by Auth


class AsyncStream:
    """Async client for **real-time WebSocket streaming**.

    Requires an already-authenticated :class:`AsyncAuth` instance. The token
    is read from the shared ``token_manager``::

        async with AsyncAuth(config) as auth:
            await auth.authenticate(otp="123456")
            async with AsyncStream(auth) as client:
                await client.streaming.connect()
                client.streaming.on_data = lambda msg: print(msg)
                await client.streaming.subscribe_symbol_trade(["VNM"])
    """

    def __init__(self, auth: AsyncAuth) -> None:
        """Wire the async streaming service onto a self-renewing WebSocket (token from Auth)."""
        self._auth = auth
        token_manager = auth.token_manager

        async def token_provider(force_refresh: bool) -> str:
            """A valid token for each (re)connect; renewed first when the server refused it."""
            if force_refresh and token_manager.has_refresh_token:
                await token_manager.refresh()
            return await token_manager.ensure_authenticated()

        ws_client = AsyncWebSocketClient(
            auth.config,
            token_provider=token_provider,
            expiry_provider=lambda: _expiry_of(token_manager),
        )
        self.streaming: AsyncStreamingService = AsyncStreamingService(ws_client)
        self.token_manager = auth.token_manager
        if auth.token_manager.access_token:
            self.streaming._ws.set_token(auth.token_manager.access_token)

    async def __aenter__(self) -> AsyncStream:
        """Enter the async context manager and return this client."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager, disconnecting the WebSocket stream."""
        await self.streaming.disconnect()


class Stream:
    """Sync client for **real-time WebSocket streaming**.

    Requires an already-authenticated :class:`Auth` instance. The token
    is read from the shared ``token_manager``::

        with Auth(config) as auth:
            auth.authenticate(otp="123456")
            with Stream(auth) as client:
                client.streaming.connect()
                client.streaming.on_data = lambda msg: print(msg)
                client.streaming.subscribe_symbol_trade(["VNM"])
                client.streaming.wait()
    """

    def __init__(self, auth: Auth) -> None:
        """Wire the sync streaming service onto a self-renewing WebSocket (token from Auth)."""
        self._auth = auth
        token_manager = auth.token_manager

        def token_provider(force_refresh: bool) -> str:
            """A valid token for each (re)connect; renewed first when the server refused it."""
            if force_refresh and token_manager.has_refresh_token:
                token_manager.refresh()
            return token_manager.ensure_authenticated()

        ws_client = WebSocketClient(
            auth.config,
            token_provider=token_provider,
            expiry_provider=lambda: _expiry_of(token_manager),
        )
        self.streaming: StreamingService = StreamingService(ws_client)
        self.token_manager = auth.token_manager
        if auth.token_manager.access_token:
            self.streaming._ws.set_token(auth.token_manager.access_token)

    def __enter__(self) -> Stream:
        """Enter the context manager and return this client."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the context manager, disconnecting the WebSocket stream."""
        self.streaming.disconnect()
