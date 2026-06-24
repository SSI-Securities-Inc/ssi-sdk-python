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

import logging

from ssi_sdk.config import Config
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
    """Build or patch a Config object."""
    if config is None:
        return Config(**kwargs)  # type: ignore[arg-type]
    if kwargs:
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
    return config


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

    def __getattr__(self, name: str) -> object:
        """Delegate unknown attributes to token_manager."""
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

    def __getattr__(self, name: str) -> object:
        """Delegate unknown attributes to token_manager."""
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
        """Wire the async streaming service onto a WebSocket seeded with the Auth token."""
        self._auth = auth
        ws_client = AsyncWebSocketClient(auth.config)
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
        """Wire the sync streaming service onto a WebSocket seeded with the Auth token."""
        self._auth = auth
        ws_client = WebSocketClient(auth.config)
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
