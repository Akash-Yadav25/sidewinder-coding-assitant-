"""Resilience, exponential backoff, and retry handling for LLM providers."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Generator, TypeVar

T = TypeVar("T")

logger = logging.getLogger("coder_agent.resilience")


@dataclass
class RetryConfig:
    """Configuration for provider retry and exponential backoff."""

    max_retries: int = 4
    initial_backoff: float = 1.0  # seconds
    max_backoff: float = 30.0  # seconds
    backoff_multiplier: float = 2.0
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)


def is_retryable_exception(exc: Exception, config: RetryConfig | None = None) -> bool:
    """Determine whether an exception is considered transient and retryable."""
    cfg = config or RetryConfig()

    # Check for HTTP status code on exception
    status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status_code is not None and isinstance(status_code, int):
        if status_code in cfg.retryable_status_codes:
            return True

    # Check exception types by name or inheritance
    exc_type_name = exc.__class__.__name__.lower()
    retryable_type_names = (
        "ratelimiterror",
        "internalservererror",
        "apiconnectionerror",
        "apitimeouterror",
        "throttlingexception",
        "requesttimeoutexception",
        "timeouterror",
        "connectionerror",
        "serviceunavailable",
        "badgateway",
    )
    if any(r in exc_type_name for r in retryable_type_names):
        return True

    # Check standard error messages
    msg = str(exc).lower()
    retryable_patterns = (
        "rate limit",
        "rate_limit",
        "too many requests",
        "throttled",
        "overloaded",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "connection reset",
        "connection closed",
    )
    if any(pattern in msg for pattern in retryable_patterns):
        return True

    # Check for AWS Botocore ClientError specific codes
    if hasattr(exc, "response") and isinstance(exc.response, dict):  # type: ignore[attr-defined]
        error_info = exc.response.get("Error", {})  # type: ignore[attr-defined]
        code = error_info.get("Code", "")
        if code in ("ThrottlingException", "RequestTimeout", "InternalServerError"):
            return True

    return False


def calculate_backoff(attempt: int, config: RetryConfig) -> float:
    """Calculate exponential backoff duration with full jitter."""
    base = min(config.max_backoff, config.initial_backoff * (config.backoff_multiplier ** (attempt - 1)))
    # Apply jitter between 0.5 * base and base to avoid stampedes
    return random.uniform(0.5 * base, base)


def execute_with_retry(
    fn: Callable[[], T],
    config: RetryConfig | None = None,
    log: logging.Logger | None = None,
) -> T:
    """Execute a callable with automatic exponential backoff retry on transient errors."""
    cfg = config or RetryConfig()
    active_logger = log or logger

    last_exception: Exception | None = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exception = exc
            if not is_retryable_exception(exc, cfg) or attempt == cfg.max_retries:
                raise

            sleep_duration = calculate_backoff(attempt, cfg)
            active_logger.warning(
                "Transient error on LLM request (attempt %d/%d): %s. Retrying in %.2fs...",
                attempt,
                cfg.max_retries,
                exc,
                sleep_duration,
            )
            time.sleep(sleep_duration)

    assert last_exception is not None
    raise last_exception


def stream_with_retry(
    stream_factory: Callable[[], Generator[str | Any, None, Any]],
    config: RetryConfig | None = None,
    log: logging.Logger | None = None,
) -> Generator[str | Any, None, Any]:
    """Execute a streaming call with retry logic before and during stream initialization."""
    cfg = config or RetryConfig()
    active_logger = log or logger

    last_exception: Exception | None = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            stream = stream_factory()
            # Yield from stream
            result = yield from stream
            return result
        except Exception as exc:
            last_exception = exc
            if not is_retryable_exception(exc, cfg) or attempt == cfg.max_retries:
                raise

            sleep_duration = calculate_backoff(attempt, cfg)
            active_logger.warning(
                "Transient error starting LLM stream (attempt %d/%d): %s. Retrying in %.2fs...",
                attempt,
                cfg.max_retries,
                exc,
                sleep_duration,
            )
            time.sleep(sleep_duration)

    assert last_exception is not None
    raise last_exception
