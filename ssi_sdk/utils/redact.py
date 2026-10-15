"""Redaction helpers: mask secrets before anything reaches a log or an exception."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Lower-cased names of fields whose values must never be logged.
SENSITIVE_KEYS = frozenset(
    {
        "apisecret",
        "api_secret",
        "apikey",
        "api_key",
        "otp",
        "pin",
        "token",
        "accesstoken",
        "access_token",
        "refreshtoken",
        "refresh_token",
        "authorization",
        "signature",
        "x-signature",
        "password",
        "privatekey",
        "private_key",
        "transactionid",
        "transaction_id",
        "accountno",
        "account_no",
        "account",
    }
)

_VISIBLE_TAIL = 4
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")


def mask(value: Any) -> str:
    """Mask a secret, keeping at most the last 4 characters (none when it is short).

    Args:
        value: Any value; it is stringified first.
    Returns:
        ``***`` for short values, otherwise ``***`` plus the last 4 characters. Values of
        8 characters or fewer reveal nothing.
    """
    text = str(value)
    if len(text) <= 2 * _VISIBLE_TAIL:
        return "***"
    return "***" + text[-_VISIBLE_TAIL:]


def mask_bearer(text: str) -> str:
    """Mask the token in any ``Bearer <token>`` occurrence inside ``text``."""
    return _BEARER.sub(lambda m: f"{m.group(1)} {mask(m.group(0).split(None, 1)[1])}", text)


def redact(data: Any) -> Any:
    """Return a copy of ``data`` with sensitive values masked, recursively.

    Dict keys are matched case-insensitively against :data:`SENSITIVE_KEYS`; list items and
    nested dicts are walked; strings have any bearer token masked. The input is not mutated.
    """
    if isinstance(data, dict):
        return {
            key: mask(value) if str(key).lower() in SENSITIVE_KEYS and value is not None
            else redact(value)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [redact(item) for item in data]
    if isinstance(data, str):
        return mask_bearer(data)
    return data


def safe_url(url: str) -> str:
    """Return ``url`` without its query string, fragment or userinfo (safe to log)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))
