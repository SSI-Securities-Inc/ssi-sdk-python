"""Configuration for SSI SDK."""

from __future__ import annotations

from dataclasses import dataclass

from ssi_sdk.constant import (
    DEFAULT_API_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RATE_LIMIT_PER_SECOND,
    DEFAULT_RETRY_DELAY,
    DEFAULT_STREAMING_URL,
    DEFAULT_TIMEOUT,
)


@dataclass
class Config:
    """SDK configuration.

    Attributes:
        client_id: Client ID for API authentication (optional, can be set via env var).
        api_url: Base URL for the SSI REST API.
        streaming_url: URL for the SSI WebSocket streaming endpoint.
        api_key: API key for API authentication.
        api_secret: API secret for API authentication.
        private_key: Private key for API authentication.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed requests.
        retry_delay: Base delay in seconds between retries (exponential backoff).
        rate_limit_per_second: Maximum requests per second (0 = unlimited).
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        proxy: Proxy URL (e.g. 'http://user:pass@host:port' or 'socks5://host:port').
    """

    client_id: str = ""
    api_url: str = DEFAULT_API_URL
    streaming_url: str = DEFAULT_STREAMING_URL
    api_key: str = ""
    api_secret: str = ""
    private_key: str = ""
    timeout: int = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    rate_limit_per_second: int = DEFAULT_RATE_LIMIT_PER_SECOND
    log_level: str = "INFO"
    proxy: str | None = None
