"""Authentication and token models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenRequest:
    """Request to obtain an access token using consumer credentials."""

    api_key: str
    api_secret: str
    otp: str | None = None

    def to_dict(self) -> dict:
        """Convert the TokenRequest to a dictionary for API requests.

        Returns:
            Dictionary with camelCase keys, including ``otp`` only when set.
        """
        result = {
            "apiKey": self.api_key,
            "apiSecret": self.api_secret,
        }
        if self.otp is not None:
            result["otp"] = self.otp
        return result


@dataclass
class Token:
    """OAuth2-style access token."""

    access_token: str
    token_type: str = "Bearer"
    expires_at: int = 0
    refresh_token: str = ""
    refresh_token_expires_at: int = 0

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
            expires_at=data.get("expiresAt", 0),
            refresh_token=data.get("refreshToken", ""),
            refresh_token_expires_at=data.get("refreshExpiresAt", 0),
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
    api_secret: str

    def to_dict(self) -> dict:
        """Convert the OTPRequest to a dictionary for API requests.

        Returns:
            Dictionary with camelCase keys ``apiKey`` and ``apiSecret``.
        """
        return {"apiKey": self.api_key, "apiSecret": self.api_secret}


@dataclass
class RefreshTokenRequest:
    """Request to refresh an access token using a refresh token."""

    refresh_token: str

    def to_dict(self) -> dict:
        """Convert the RefreshTokenRequest to a dictionary for API requests.

        Returns:
            Dictionary with the camelCase key ``refreshToken``.
        """
        return {"refreshToken": self.refresh_token}
