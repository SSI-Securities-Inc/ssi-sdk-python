"""Logging utility for SSI SDK."""

from __future__ import annotations

import logging
import sys


class MillisecondsFormatter(logging.Formatter):
    """Formatter that supports millisecond resolution in datefmt using %f."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        if datefmt and "%f" in datefmt:
            datefmt = datefmt.replace("%f", f"{int(record.msecs):03d}")
        return super().formatTime(record, datefmt)


def get_logger(name: str = "ssi_sdk", level: str = "INFO") -> logging.Logger:
    """Get a configured logger instance.

    Args:
        name: Logger name.
        level: Logging level string.

    Returns:
        Configured logger.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = MillisecondsFormatter(
            "%(asctime)s %(levelname)s [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S.%f",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
