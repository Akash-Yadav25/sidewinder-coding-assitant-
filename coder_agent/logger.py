"""Structured logging for Coder Agent directed to stderr."""

from __future__ import annotations

import logging
import sys


def setup_logger(level: str = "info") -> logging.Logger:
    """Configure and return the agent logger writing to stderr."""
    logger = logging.getLogger("coder_agent")

    # Clear existing handlers to prevent duplicate logging
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    return logger
