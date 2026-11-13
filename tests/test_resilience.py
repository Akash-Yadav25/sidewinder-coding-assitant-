"""Unit tests for provider resilience and exponential backoff."""

from __future__ import annotations

import pytest

from coder_agent.providers.resilience import (
    RetryConfig,
    calculate_backoff,
    execute_with_retry,
    is_retryable_exception,
    stream_with_retry,
)


class CustomRateLimitError(Exception):
    status_code = 429


class CustomInternalServerError(Exception):
    status_code = 500


class CustomAuthError(Exception):
    status_code = 401


def test_is_retryable_exception():
    cfg = RetryConfig()
    assert is_retryable_exception(CustomRateLimitError("Rate limit reached"), cfg)
    assert is_retryable_exception(CustomInternalServerError("Internal server error"), cfg)
    assert not is_retryable_exception(CustomAuthError("Unauthorized"), cfg)
    assert not is_retryable_exception(ValueError("Invalid argument"), cfg)
    assert is_retryable_exception(Exception("Connection reset by peer"), cfg)
    assert is_retryable_exception(Exception("Service temporarily unavailable"), cfg)


def test_calculate_backoff():
    cfg = RetryConfig(initial_backoff=1.0, max_backoff=10.0, backoff_multiplier=2.0)
    for attempt in range(1, 5):
        backoff = calculate_backoff(attempt, cfg)
        assert 0 < backoff <= 10.0


def test_execute_with_retry_immediate_success():
    calls = 0

    def work():
        nonlocal calls
        calls += 1
        return "success"

    result = execute_with_retry(work, RetryConfig(max_retries=3))
    assert result == "success"
    assert calls == 1


def test_execute_with_retry_recovers(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = 0

    def work():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise CustomRateLimitError("Too many requests")
        return "recovered"

    result = execute_with_retry(work, RetryConfig(max_retries=4, initial_backoff=0.01))
    assert result == "recovered"
    assert calls == 3


def test_execute_with_retry_non_retryable_fails_fast():
    calls = 0

    def work():
        nonlocal calls
        calls += 1
        raise ValueError("Bad parameter")

    with pytest.raises(ValueError, match="Bad parameter"):
        execute_with_retry(work, RetryConfig(max_retries=4))

    assert calls == 1


def test_execute_with_retry_exhausted(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = 0

    def work():
        nonlocal calls
        calls += 1
        raise CustomRateLimitError("Persistent rate limit")

    with pytest.raises(CustomRateLimitError):
        execute_with_retry(work, RetryConfig(max_retries=3, initial_backoff=0.01))

    assert calls == 3


def test_stream_with_retry_success():
    def create_stream():
        yield "chunk1"
        yield "chunk2"
        return "done"

    chunks = list(stream_with_retry(create_stream, RetryConfig(max_retries=3)))
    assert chunks == ["chunk1", "chunk2"]


def test_stream_with_retry_recovers(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)

    attempts = 0

    def create_stream():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise CustomRateLimitError("Stream init failed")
        yield "ok"

    chunks = list(stream_with_retry(create_stream, RetryConfig(max_retries=3, initial_backoff=0.01)))
    assert chunks == ["ok"]
    assert attempts == 2
