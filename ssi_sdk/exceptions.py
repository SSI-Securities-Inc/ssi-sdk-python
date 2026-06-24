"""Custom exceptions for SSI SDK."""


class SSIError(Exception):
    """Base exception for all SSI SDK errors."""

    def __init__(
        self,
        message: str = "",
        code: str | None = None,
        status_code: int | None = None,
        response_body: dict | None = None,
        headers: dict | None = None,
    ):
        """Initialize the error with optional message, code, and HTTP context.

        Args:
            message: Human-readable error description.
            code: SSI/application-specific error code, if any.
            status_code: HTTP status code associated with the error, if any.
            response_body: Parsed response body returned by the API, if any.
            headers: HTTP response headers; defaults to an empty dict.
        """
        self.message = message
        self.code = code
        self.status_code = status_code
        self.response_body = response_body
        self.headers = headers or {}
        super().__init__(self.message)


class AuthenticationError(SSIError):
    """Raised when authentication fails (invalid credentials, expired token, etc.)."""


class APIError(SSIError):
    """Raised when the SSI API returns an error response."""

    def __init__(
        self,
        message: str = "",
        code: str | None = None,
        status_code: int | None = None,
        response_body: dict | None = None,
    ):
        """Initialize the API error with message, code, and HTTP response context.

        Args:
            message: Human-readable error description.
            code: SSI/application-specific error code, if any.
            status_code: HTTP status code returned by the API, if any.
            response_body: Parsed response body returned by the API, if any.
        """
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message, code)


class WebSocketError(SSIError):
    """Raised when a WebSocket connection or communication error occurs."""


class ValidationError(SSIError):
    """Raised when input validation fails."""


class RateLimitError(SSIError):
    """Raised when API rate limit is exceeded."""

    def __init__(self, message: str = "", retry_after: float | None = None):
        """Initialize the rate-limit error with a message and optional retry delay.

        Args:
            message: Human-readable error description.
            retry_after: Seconds to wait before retrying, from the API, if any.
        """
        self.retry_after = retry_after
        super().__init__(message, code="RATE_LIMITED")
