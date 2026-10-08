"""Authentication and token models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ssi_sdk.constant import TOKEN_EXPIRY_SKEW_SECONDS
from ssi_sdk.utils.converter import to_int

# Epoch values at or above this are milliseconds (10^10 s is the year 2286).
_MS_THRESHOLD = 10**10


def _to_seconds(value: object) -> int:
    """Normalize an epoch to seconds.

    The server sends seconds; a millisecond value (>= 1e10) is divided by 1000 defensively.
    None, garbage and negatives become 0 (meaning "unknown/expired").
    """
    seconds = to_int(value)
    if seconds >= _MS_THRESHOLD:
        seconds //= 1000
    return max(seconds, 0)



@dataclass
class TokenRequest:
    """Request to obtain an access token using consumer credentials."""

    api_key: str
    api_secret: str = field(repr=False)
    otp: str | None = field(default=None, repr=False)
    transaction_id: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        """Convert the TokenRequest to a dictionary for API requests.

        Returns:
            Dictionary with camelCase keys. ``otp`` is included only when set
            (normal OTP flow); ``transactionId`` is included only when set
            (Smart OTP flow) — the two are mutually exclusive.
        """
        result = {
            "apiKey": self.api_key,
            "apiSecret": self.api_secret,
        }
        if self.otp is not None:
            result["otp"] = self.otp
        if self.transaction_id is not None:
            result["transactionId"] = self.transaction_id
        return result


@dataclass
class Token:
    """OAuth2-style access token.

    Attributes:
        access_token: Bearer token for REST/WebSocket calls (hidden from ``repr``).
        token_type: Always ``"Bearer"``.
        expires_at: Access token expiry, epoch **seconds** (0 = unknown, treated as
            expired).
        refresh_token: Token used to renew the access token (hidden from ``repr``).
        refresh_token_expires_at: Refresh token expiry, epoch seconds.
    """

    access_token: str = field(repr=False)
    token_type: str = "Bearer"
    expires_at: int = 0
    refresh_token: str = field(default="", repr=False)
    refresh_token_expires_at: int = 0

    @property
    def effective_expires_at(self) -> int:
        """Epoch seconds after which this token set can no longer be used without a new OTP.

        The earlier of the access-token and refresh-token expiries, ignoring a value that
        is unknown (<= 0). 0 when both are unknown.
        """
        known = [t for t in (self.expires_at, self.refresh_token_expires_at) if t > 0]
        return min(known) if known else 0

    @property
    def can_refresh(self) -> bool:
        """Whether the refresh token is present and not (about to be) expired.

        An unknown refresh expiry (<= 0) is given the benefit of the doubt: the server
        will reject it if it is in fact dead.
        """
        if not self.refresh_token:
            return False
        if self.refresh_token_expires_at <= 0:
            return True
        return time.time() < self.refresh_token_expires_at - TOKEN_EXPIRY_SKEW_SECONDS

    @classmethod
    def from_dict(cls, data: dict) -> Token:
        """Create a Token instance from a dictionary.

        Args:
            data: API response with camelCase keys (e.g. ``accessToken``, ``expiresAt``).
        Returns:
            A Token populated from the dictionary, using defaults for missing keys.
        """
        return cls(
            access_token=data.get("accessToken", ""),
            token_type=data.get("tokenType", "Bearer"),
            expires_at=_to_seconds(data.get("expiresAt")),
            refresh_token=data.get("refreshToken", ""),
            refresh_token_expires_at=_to_seconds(data.get("refreshExpiresAt")),
        )

    def to_dict(self) -> dict:
        """Convert the Token instance to a dictionary.

        Returns:
            Dictionary with camelCase keys mirroring the API token schema.
        """
        return {
            "accessToken": self.access_token,
            "tokenType": self.token_type,
            "expiresAt": self.expires_at,
            "refreshToken": self.refresh_token,
            "refreshExpiresAt": self.refresh_token_expires_at,
        }


@dataclass
class OTPRequest:
    """Request to get OTP for trading operations."""

    api_key: str
    api_secret: str = field(repr=False)

    def to_dict(self) -> dict:
        """Convert the OTPRequest to a dictionary for API requests.

        Returns:
            Dictionary with camelCase keys ``apiKey`` and ``apiSecret``.
        """
        return {"apiKey": self.api_key, "apiSecret": self.api_secret}


@dataclass
class RefreshTokenRequest:
    """Request to refresh an access token using a refresh token."""

    refresh_token: str = field(repr=False)

    def to_dict(self) -> dict:
        """Convert the RefreshTokenRequest to a dictionary for API requests.

        Returns:
            Dictionary with the camelCase key ``refreshToken``.
        """
        return {"refreshToken": self.refresh_token}


@dataclass
class OTPResponse:
    """Response to an OTP request.

    ``transaction_id`` is only present for Smart OTP (push-approval); SMS/email OTP
    responses carry just a message.

    Attributes:
        message: Server message (for a rejection, the reason).
        transaction_id: Smart OTP transaction id; ``None`` for SMS/e-mail OTP.
    """

    message: str = ""
    transaction_id: str | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> OTPResponse:
        """Create an OTPResponse from the ``requestOtp`` response body.

        Args:
            data: Response dict; ``message``/``msg`` and ``transactionId`` are optional.
        Returns:
            A populated OTPResponse.
        """
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        transaction_id = payload.get("transactionId")
        return cls(
            message=str(payload.get("message") or payload.get("msg") or ""),
            transaction_id=str(transaction_id) if transaction_id else None,
        )
