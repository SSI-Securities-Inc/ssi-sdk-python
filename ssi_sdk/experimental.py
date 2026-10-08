"""EXPERIMENTAL features that are not part of the stable facade.

Trading WebSocket (order entry over ``/ws/v3/trading``): the server side has not been announced
as released, so use it only against an environment you were told supports it. It is
not exported from ``ssi_sdk`` and ``Trading``/``Stream`` never connect to it.

    from ssi_sdk.experimental import async_trading_ws

    async with AsyncAuth(config) as auth:
        await auth.ensure_authenticated(otp="123456")
        ws = await async_trading_ws(auth)       # connects to Config.trading_ws_url
        ack = await ws.place_order(...)         # PD ack; the outcome comes via order events
        await ws.close()
"""

from __future__ import annotations

from typing import Any

from ssi_sdk.client import AsyncAuth, Auth
from ssi_sdk.exceptions import TradingWSError
from ssi_sdk.services.trading_ws import AsyncTradingWSService, TradingWSService
from ssi_sdk.transport.trading_ws import (
    AsyncTradingWSClient,
    TradingWSClient,
    TradingWSResponse,
)

__all__ = [
    "AsyncTradingWSClient",
    "AsyncTradingWSService",
    "TradingWSClient",
    "TradingWSError",
    "TradingWSResponse",
    "TradingWSService",
    "async_trading_ws",
    "trading_ws",
]


async def async_trading_ws(auth: AsyncAuth, **options: Any) -> AsyncTradingWSService:
    """Connect an async trading WebSocket using the token and keys of ``auth``.

    The URL comes from ``Config.trading_ws_domain`` (the one trading-WS setting; everything else
    is the shared ``Config``). ``options`` are the optional keyword arguments of
    :class:`AsyncTradingWSClient`: ``signature_encoding`` (``"auto"``/``"base64"``/``"hex"``),
    ``request_timeout``, ``user_agent``, ``handshake_grace``, ``respect_rate_limit``,
    ``max_rate_limit_wait``,
    ``ping_interval``.

    The returned service has a ``close()`` coroutine (and an ``on_event`` hook on ``.client``).

    Raises:
        TradingWSError: If the server refuses the connection after the upgrade (401/403/429/500).
    """
    config = auth.config
    options.setdefault("request_timeout", float(config.timeout or 10))
    options.setdefault("user_agent", config.user_agent)
    client = AsyncTradingWSClient(
        config.trading_ws_url,
        auth.token_manager.ensure_authenticated,
        config.private_key,
        **options,
    )
    await client.connect()
    return AsyncTradingWSService(client, config)


def trading_ws(auth: Auth, **options: Any) -> TradingWSService:
    """Connect a sync trading WebSocket using the token and keys of ``auth``.

    Same ``options`` as :func:`async_trading_ws`; the URL is ``Config.trading_ws_url``.
    """
    config = auth.config
    options.setdefault("request_timeout", float(config.timeout or 10))
    options.setdefault("user_agent", config.user_agent)
    client = TradingWSClient(
        config.trading_ws_url,
        auth.token_manager.ensure_authenticated,
        config.private_key,
        **options,
    )
    client.connect()
    return TradingWSService(client, config)
