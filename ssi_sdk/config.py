"""Configuration for SSI SDK."""

from __future__ import annotations

from dataclasses import dataclass, field

from ssi_sdk.constant import (
    DEFAULT_API_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_OTP_POLL_INTERVAL,
    DEFAULT_OTP_POLL_MAX_WAIT,
    DEFAULT_RATE_LIMIT_PER_SECOND,
    DEFAULT_RETRY_DELAY,
    DEFAULT_STREAMING_URL,
    DEFAULT_TIMEOUT,
    DEFAULT_TRADING_API_DOMAIN,
    DEFAULT_TRADING_WS_DOMAIN,
    MAX_BATCH_ORDERS,
    TRADING_WS_PATH,
)
from ssi_sdk.exceptions import ValidationError

# Endpoint fields and their defaults: not passed, ``None`` or blank all mean the default.
_ENDPOINT_DEFAULTS = {
    "api_url": DEFAULT_API_URL,
    "streaming_url": DEFAULT_STREAMING_URL,
    "trading_api_domain": DEFAULT_TRADING_API_DOMAIN,
    "trading_ws_domain": DEFAULT_TRADING_WS_DOMAIN,
}


@dataclass
class Config:
    """SDK configuration.

    ``api_url``, ``streaming_url``, ``trading_api_domain`` and ``trading_ws_domain`` fall back
    to their defaults (``ssi_sdk.constant``) when not passed, ``None`` or blank.

    Attributes:
        client_id: Client ID for API authentication (optional, can be set via env var).
        api_url: Base URL for the SSI REST API.
        streaming_url: URL for the SSI WebSocket streaming endpoint.
        trading_api_domain: URL of the trading REST API (orders, FCO, account, portfolio), like
            ``api_url`` with its ``https://``. While it stays at the default it follows ``api_url``
            (so changing only ``api_url`` moves trading too); set another host to split them.
            Empty means the same, and a bare ``host[:port]`` gets ``https://``. Auth and market data
            always use ``api_url``. Change it if SSI moves trading to another domain.
        trading_ws_domain: URL of the experimental trading WebSocket, like ``streaming_url`` with
            its ``wss://`` (default ``wss://api.ssi.com.vn/ws/v3/trading``; its host differs from
            ``streaming_url``'s). A bare ``host[:port]`` gets ``wss://`` and ``/ws/v3/trading``;
            a URL without a path gets the path. Change it if SSI renames the domain.
        api_key: API key for API authentication.
        api_secret: API secret for API authentication.
        private_key: Private key for API authentication.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed requests.
        retry_delay: Base delay in seconds between retries (exponential backoff).
        rate_limit_per_second: Maximum requests per second (0 = unlimited).
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        max_batch_orders: Most orders in one batch request. The server's default is 20 (it is
            configurable): raise this only if SSI raised it. Bigger batches are refused locally.
        proxy: Proxy URL (e.g. 'http://user:pass@host:port' or 'socks5://host:port').
        user_agent: Optional User-Agent for HTTP requests and order payloads.
        auto_reconnect: Re-open a dropped streaming socket automatically.
        otp_poll_interval: Seconds between Smart OTP approval polls.
        otp_poll_max_wait: Total seconds to keep polling for Smart OTP approval.
    """

    client_id: str = ""
    api_url: str = DEFAULT_API_URL
    streaming_url: str = DEFAULT_STREAMING_URL
    trading_api_domain: str = DEFAULT_TRADING_API_DOMAIN
    trading_ws_domain: str = DEFAULT_TRADING_WS_DOMAIN
    api_key: str = ""
    api_secret: str = field(default="", repr=False)
    private_key: str = field(default="", repr=False)
    timeout: int = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    rate_limit_per_second: int = DEFAULT_RATE_LIMIT_PER_SECOND
    log_level: str = "INFO"
    max_batch_orders: int = MAX_BATCH_ORDERS
    proxy: str | None = None
    user_agent: str | None = None
    auto_reconnect: bool = True
    otp_poll_interval: float = DEFAULT_OTP_POLL_INTERVAL
    otp_poll_max_wait: float = DEFAULT_OTP_POLL_MAX_WAIT

    def __post_init__(self) -> None:
        """Fill the four endpoints that were left out, ``None`` or blank with their defaults."""
        for name, default in _ENDPOINT_DEFAULTS.items():
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                setattr(self, name, default)
        if not isinstance(self.max_batch_orders, int) or self.max_batch_orders < 1:
            self.max_batch_orders = MAX_BATCH_ORDERS

    @property
    def trading_api_url(self) -> str:
        """Base URL of the trading REST API: ``trading_api_domain``, or ``api_url`` when that is
        empty or still the default (so it follows ``api_url``).

        A bare ``host`` or ``host:port`` becomes ``https://host``; a value with ``http://`` /
        ``https://`` keeps its scheme. Any path or trailing slash is dropped.

        Raises:
            ValidationError: If the value has a scheme other than ``http``/``https``.
        """
        value = (self.trading_api_domain or "").strip()
        if not value or value.rstrip("/") == DEFAULT_TRADING_API_DOMAIN:
            return self.api_url.rstrip("/")
        if "://" not in value:
            value = f"https://{value}"
        scheme, rest = value.split("://", 1)
        if scheme.lower() not in ("http", "https"):
            raise ValidationError(f"trading_api_domain must be http(s), got '{scheme}://'")
        return f"{scheme.lower()}://{rest.split('/', 1)[0]}"

    @property
    def trading_ws_url(self) -> str:
        """The trading WebSocket URL built from ``trading_ws_domain`` (always ``wss://``).

        ``"api.ssi.com.vn"`` -> ``wss://api.ssi.com.vn/ws/v3/trading``; ``"host:8443"`` keeps the
        port; a value that already starts with ``wss://`` is used as is (the path is appended only
        when the value has none).
        """
        value = (self.trading_ws_domain or "").strip().rstrip("/")
        if "://" not in value:
            value = f"wss://{value}"
        scheme_end = value.index("://") + 3
        if "/" not in value[scheme_end:]:
            value += TRADING_WS_PATH
        return value
