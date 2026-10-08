"""HTTP status code enums for SSI SDK."""

from enum import IntEnum

from ssi_sdk.enums.base import BaseEnum


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


class ServerErrorCode(BaseEnum):
    """Application error codes the FastConnect server returns in ``{"code", "msg"}``.

    Meanings come from the server's auth/trading/data code (see ``SDK_SERVER_SPEC_MATCH``).
    A few numbers are reused in different places; the later names are aliases of the first
    (``400104`` is both "OTP could not be sent" and "symbol is required").
    ``from_value`` returns ``None`` for any other code, so an unknown code never raises.
    Note the signature codes (4010xx) do not line up with the server's own
    ``error-code-mapping.json`` (server issue S1): trust the number, not the mapped text.
    """

    # -- auth / account / OTP
    CREDENTIAL_NOT_LINKED_TO_CLIENT = 400101
    TWO_FA_INFO_ERROR = 400102
    TWO_FA_INFO_MISSING = 400103
    OTP_SEND_FAILED = 400104
    SYMBOL_REQUIRED = 400104  # data validators reuse the number
    PUSH_APPROVAL_CREATE_FAILED = 400171
    OTP_VERIFICATION_FAILED = 401100
    REFRESH_TOKEN_INVALID = 401101
    REFRESH_CLIENT_MISSING = 401102
    REFRESH_TOKEN_REVOKED_OR_EXPIRED = 401103  # reusing a refresh token revokes the whole apiKey
    REFRESH_API_KEY_GONE = 401104
    INVALID_API_CREDENTIAL = 401105
    TOKEN_WITHOUT_OTP = 401105  # the signature validator reuses the number
    PUSH_APPROVAL_NOT_FOUND = 401113
    PUSH_APPROVAL_PENDING = 401114  # arrives as HTTP 202, not as an error status
    SMART_OTP_PENDING = 401114
    PUSH_APPROVAL_REJECTED = 401115
    PUSH_APPROVAL_FOREIGN_TRANSACTION = 401116
    NO_SCOPE_GRANTED = 403100

    # -- request signature (X-Signature / WebSocket ``signature``)
    SIGNATURE_MISSING = 401006
    SIGNATURE_BODY_EMPTY = 401008
    SIGNATURE_MISMATCH = 401013
    SIGNATURE_INVALID = 401013

    # -- trading
    MODIFY_PRICE_AND_QUANTITY = 400107
    REPLAY_WINDOW_EXCEEDED = 400111

    # -- market data validators
    SYMBOL_INVALID_CHARACTERS = 400006
    FROM_AFTER_TO = 400202
    BOARD_NOT_ALLOWED = 400208
    TIMEFRAME_NOT_SUPPORTED = 400210  # also used when from/to are empty (server issue V10)
    DATE_FORMAT_INVALID = 400213
    INDEX_SUMMARY_NEEDS_ONE_OF = 504207
    SECURITIES_INFO_NEEDS_ONE_OF = 504208
    SECURITIES_SUMMARY_NEEDS_SYMBOL_XOR_INDEX = 504209
