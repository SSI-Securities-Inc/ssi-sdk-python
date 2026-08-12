"""Cryptographic utilities: signing, encryption, and decryption."""

from __future__ import annotations

import base64
import hashlib
from xml.etree.ElementTree import fromstring

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


def sign(data: str, private_key: str) -> str:
    """Sign data with an RSA PKCS#1 v1.5 SHA-256 signature using only the standard library.

    Args:
        data: The plaintext string to sign.
        private_key: Base64-encoded XML RSA private key string.
    Returns:
        The hexadecimal-encoded RSA signature.
    """
    n, d = get_rsa_key(private_key)

    digest = hashlib.sha256(data.encode("utf-8")).digest()
    digest_info = _SHA256_DER_PREFIX + digest

    key_len = (n.bit_length() + 7) // 8
    pad_len = key_len - len(digest_info) - 3
    padded = b"\x00\x01" + b"\xff" * pad_len + b"\x00" + digest_info

    m = int.from_bytes(padded, byteorder="big")
    s = pow(m, d, n)  # RSA private-key operation
    return s.to_bytes(key_len, byteorder="big").hex()
