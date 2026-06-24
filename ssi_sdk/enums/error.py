"""HTTP status code enums for SSI SDK."""

from enum import IntEnum


class HTTPStatus(IntEnum):
    """Standard HTTP status codes used by the SSI API."""

    # 2xx Success
    OK = 200
    NO_CONTENT = 204

    # 4xx Client Errors
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    UNPROCESSABLE_ENTITY = 422
    TOO_MANY_REQUESTS = 429

    # 5xx Server Errors
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

    @property
    def is_auth_error(self) -> bool:
        """Check whether this status indicates an authentication/authorization failure.

        Returns:
            bool: True if the status is 401 Unauthorized or 403 Forbidden.
        """
        return self in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)

    @property
    def is_rate_limit(self) -> bool:
        """Check whether this status indicates rate limiting.

        Returns:
            bool: True if the status is 429 Too Many Requests.
        """
        return self == HTTPStatus.TOO_MANY_REQUESTS

    @property
    def is_client_error(self) -> bool:
        """Check whether this status is a 4xx client error.

        Returns:
            bool: True if the status code is in the range 400-499.
        """
        return 400 <= self < 500

    @property
    def is_server_error(self) -> bool:
        """Check whether this status is a 5xx server error.

        Returns:
            bool: True if the status code is 500 or greater.
        """
        return self >= 500
