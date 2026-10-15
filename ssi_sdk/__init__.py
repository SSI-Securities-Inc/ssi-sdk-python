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
