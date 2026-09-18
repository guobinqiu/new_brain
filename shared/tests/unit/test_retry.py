import pytest

from shared.config import RetryConfig
from shared.upstream import UpstreamServiceError


def test_retry_attempts_include_first_call(monkeypatch):
    from shared import retry

    monkeypatch.setattr(retry.time, "sleep", lambda seconds: None)
    calls = []

    def operation():
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise UpstreamServiceError(service="test", error="temporary", retryable=True, status_code=503)
        return "ok"

    assert retry.retry_call(operation, RetryConfig(max_attempts=3, interval_seconds=0.2)) == "ok"
    assert calls == [1, 2, 3]


def test_retry_does_not_retry_non_retryable_error(monkeypatch):
    from shared import retry

    monkeypatch.setattr(retry.time, "sleep", lambda seconds: None)
    calls = []

    def operation():
        calls.append(1)
        raise UpstreamServiceError(service="test", error="bad request", retryable=False, status_code=400)

    with pytest.raises(UpstreamServiceError):
        retry.retry_call(operation, RetryConfig(max_attempts=3, interval_seconds=0.2))
    assert calls == [1]
