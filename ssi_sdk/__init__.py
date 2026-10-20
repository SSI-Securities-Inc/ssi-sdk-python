"""SSI Python SDK."""

from ssi_sdk._version import __version__
from ssi_sdk.client import (
    AsyncAuth,
    AsyncData,
    AsyncStream,
    AsyncTrading,
    Auth,
    Data,
    Stream,
    Trading,
    async_trading_ws,
    trading_ws,
)
from ssi_sdk.config import Config
from ssi_sdk.exceptions import (
    APIError,
    AuthenticationError,
    DuplicateRequestError,
    RateLimitError,
    ReauthenticationRequired,
    SmartOTPPendingError,
    SmartOTPRejectedError,
    SSIError,
    TradingWSError,
    ValidationError,
    WebSocketError,
)
from ssi_sdk.services.trading_ws import AsyncTradingWSService, TradingWSService
from ssi_sdk.transport.trading_ws import (
    AsyncTradingWSClient,
    TradingWSClient,
    TradingWSResponse,
)

__all__ = [
    "__version__",
    # Specialized clients
    "AsyncAuth",
    "Auth",
    "AsyncData",
    "Data",
    "AsyncTrading",
    "Trading",
    "AsyncStream",
    "Stream",
    # Trading WebSocket (explicit opt-in)
    "trading_ws",
    "async_trading_ws",
    "TradingWSService",
    "AsyncTradingWSService",
    "TradingWSClient",
    "AsyncTradingWSClient",
    "TradingWSResponse",
    # Config
    "Config",
    # Exceptions
    "APIError",
    "AuthenticationError",
    "DuplicateRequestError",
    "ReauthenticationRequired",
    "SmartOTPPendingError",
    "SmartOTPRejectedError",
    "TradingWSError",
    "SSIError",
    "RateLimitError",
    "ValidationError",
    "WebSocketError",
]
