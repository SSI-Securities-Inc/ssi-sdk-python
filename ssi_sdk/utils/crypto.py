"""Cryptographic utilities: signing, encryption, and decryption."""

from __future__ import annotations

import base64
import hashlib
import math
import secrets
from typing import Literal
from xml.etree.ElementTree import fromstring

from ssi_sdk.exceptions import ValidationError

# DER prefix for SHA-256 AlgorithmIdentifier (PKCS#1 v1.5 DigestInfo header)
_SHA256_DER_PREFIX = bytes(
    [
        0x30,
        0x31,
        0x30,
        0x0D,
        0x06,
        0x09,
        0x60,
        0x86,
        0x48,
        0x01,
        0x65,
        0x03,
        0x04,
        0x02,
        0x01,
        0x05,
        0x00,
        0x04,
        0x20,
    ]
)


def get_rsa_key_full(private_key: str):
    """Parse the XML key into ``(n, e, d)``; ``e`` is ``None`` when the XML has no Exponent."""
    key_bytes = base64.b64decode(private_key.encode("utf-8"))
    root = fromstring(key_bytes.decode("utf-8"))

    def _get_int(tag: str) -> int | None:
        node = root.find(tag)
        if node is None or not node.text:
            return None
        return int.from_bytes(base64.b64decode(node.text), byteorder="big")

    return _get_int("Modulus"), _get_int("Exponent"), _get_int("D")


def get_rsa_key(private_key: str):
    """Parse a base64-encoded XML RSA key into its modulus and private exponent.

    Args:
        private_key: Base64-encoded XML RSA private key string.
    Returns:
        A tuple ``(n, d)`` where ``n`` is the modulus and ``d`` is the private exponent.
    """
    key_bytes = base64.b64decode(private_key.encode("utf-8"))
    root = fromstring(key_bytes.decode("utf-8"))

    def _get_int(tag: str) -> int:
        """Decode the base64 text of the given XML tag into a big-endian integer."""
        return int.from_bytes(base64.b64decode(root.find(tag).text), byteorder="big")

    return _get_int("Modulus"), _get_int("D")


def sign(data: str, private_key: str, encoding: Literal["hex", "base64"] = "hex") -> str:
    """Sign data with an RSA PKCS#1 v1.5 SHA-256 signature using only the standard library.

    Args:
        data: The plaintext string to sign.
        private_key: Base64-encoded XML RSA private key string.
        encoding: ``"hex"`` (REST ``X-Signature``) or ``"base64"`` (trading WebSocket, as its
            public documentation states).
    Returns:
        The RSA signature in the requested encoding.
    Raises:
        ValidationError: If the key is missing/malformed or the encoding is unknown.
    """
    if not private_key:
        raise ValidationError("private_key is required to sign this request")
    try:
        n, e, d = get_rsa_key_full(private_key)
        if n is None or d is None:
            raise ValueError("incomplete key")
    except Exception:  # noqa: BLE001  (never echo key material or parser internals)
        raise ValidationError(
            "private_key is not a valid base64-encoded XML RSA key"
        ) from None

    digest = hashlib.sha256(data.encode("utf-8")).digest()
    digest_info = _SHA256_DER_PREFIX + digest

    key_len = (n.bit_length() + 7) // 8
    pad_len = key_len - len(digest_info) - 3
    padded = b"\x00\x01" + b"\xff" * pad_len + b"\x00" + digest_info

    m = int.from_bytes(padded, byteorder="big")
    s = _private_op(m, n, e, d)
    raw = s.to_bytes(key_len, byteorder="big")
    if encoding == "base64":
        return base64.b64encode(raw).decode("ascii")
    if encoding != "hex":
        raise ValidationError(f"signature encoding must be 'hex' or 'base64', got {encoding!r}")
    return raw.hex()


def _private_op(m: int, n: int, e: int | None, d: int) -> int:
    """RSA private-key operation with base blinding and a result check.

    Blinding randomises the value ``d`` is applied to, which blunts timing attacks (pure
    Python cannot be constant-time; a vetted library would be better but is not a dependency
    of this SDK). With the public exponent known the signature is verified before it is
    returned, so a faulty computation can never leak a bad signature.
    """
    if e is None:
        return pow(m, d, n)
    while True:
        r = secrets.randbelow(n - 3) + 2
        if math.gcd(r, n) == 1:
            break
    blinded = (m * pow(r, e, n)) % n
    s = (pow(blinded, d, n) * pow(r, -1, n)) % n
    if pow(s, e, n) != m:
        raise ValidationError("signing failed an internal consistency check")
    return s
