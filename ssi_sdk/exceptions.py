"""Custom exceptions for SSI SDK."""


class SSIError(Exception):
    """Base exception for all SSI SDK errors."""

    def __init__(
        self,
        message: str = "",
        code: str | int | None = None,
        status_code: int | None = None,
        response_body: dict | None = None,
        headers: dict | None = None,
    ):
        """Initialize the error with optional message, code, and HTTP context.

        Args:
            message: Human-readable error description.
            code: SSI/application-specific error code (the server's ``code``), if any.
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
    """Raised when the SSI API returns an error response.

    ``code`` is the server's own error code (e.g. ``400107``) when the body carried one,
    otherwise the HTTP status as a string; ``status_code`` is always the HTTP status.
    """

    def __init__(
        self,
        message: str = "",
        code: str | int | None = None,
        status_code: int | None = None,
        response_body: dict | None = None,
        headers: dict | None = None,
    ):
        """Initialize the API error with message, code, and HTTP response context.

        Args:
            message: Human-readable error description.
            code: SSI/application-specific error code, if any.
            status_code: HTTP status code returned by the API, if any.
            response_body: Parsed response body returned by the API, if any.
            headers: HTTP response headers, if any.
        """
        super().__init__(message, code, status_code, response_body, headers)


class WebSocketError(SSIError):
    """Raised when a WebSocket connection or communication error occurs."""


class TradingWSError(WebSocketError):
    """An error frame from the trading WebSocket: ``{"id", "status", "error": {...}}``.

    Carries the server's status, string code and message. It never carries the signed
    ``params`` (they hold account numbers).
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        """Build the error from the frame's status and ``error`` object."""
        super().__init__(f"{status} {code}: {message}", code=code, status_code=status)
        self.status = status
        self.error_code = code
        self.server_message = message


class ValidationError(SSIError):
    """Raised when input validation fails."""


class RateLimitError(SSIError):
    """Raised when API rate limit is exceeded.

    The server sends ``X-RateLimit-Limit``/``X-RateLimit-Remaining`` and, on 429,
    ``Retry-After``. It does not send a reset time, so ``reset`` stays ``None``
    unless a caller supplies one.
    """

    def __init__(
        self,
        message: str = "",
        retry_after: float | None = None,
        *,
        code: str | int | None = "RATE_LIMITED",
        status_code: int | None = 429,
        response_body: dict | None = None,
        headers: dict | None = None,
        limit: int | None = None,
        remaining: int | None = None,
        reset: float | None = None,
    ):
        """Initialize the rate-limit error with a message and optional rate-limit context.

        Args:
            message: Human-readable error description.
            retry_after: Seconds to wait before retrying, from the API, if any.
            code: Server error code if the body carried one.
            status_code: HTTP status code (429 by default).
            response_body: Parsed response body, if any.
            headers: HTTP response headers, if any.
            limit: Request quota from ``X-RateLimit-Limit``, if sent.
            remaining: Remaining quota from ``X-RateLimit-Remaining``, if sent.
            reset: Quota reset time; the server does not send one, so usually ``None``.
        """
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.reset = reset
        super().__init__(message, code, status_code, response_body, headers)


class SmartOTPPendingError(AuthenticationError):
    """Smart OTP push-approval has not been confirmed on the device yet (HTTP 202 / 401114)."""


class SmartOTPRejectedError(AuthenticationError):
    """Smart OTP approval can no longer succeed (rejected, expired or unknown transaction)."""


class ReauthenticationRequired(AuthenticationError):
    """The session cannot be refreshed; the user must authenticate again with a new OTP."""


class DuplicateRequestError(APIError):
    """HTTP 409: ``clientRequestId``/``batchRequestId`` was already used today.

    The SDK never retries the order under a new id; the original order may be live.
    """
