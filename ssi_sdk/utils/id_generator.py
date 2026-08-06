"""Unique ID generation utilities."""

from math import ceil, log
from os import urandom

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SIZE = 20


def generate_request_id(alphabet: str = _ALPHABET, size: int = _SIZE) -> str:
    """Generate a cryptographically-random nanoid-style client request ID.

    Args:
        alphabet: The set of characters to draw from when building the ID.
        size: The number of characters in the generated ID.
    Returns:
        A random ID string of length ``size`` composed of characters from ``alphabet``.
    """
    alphabet_len = len(alphabet)

    mask = 1
    if alphabet_len > 1:
        mask = (2 << int(log(alphabet_len - 1) / log(2))) - 1
    step = int(ceil(1.6 * mask * size / alphabet_len))

    result = ""
    while True:
        random_bytes = bytearray(urandom(step))
        for byte in random_bytes:
            random_byte = byte & mask
            if random_byte < alphabet_len:
                result += alphabet[random_byte]
                if len(result) == size:
                    return result
