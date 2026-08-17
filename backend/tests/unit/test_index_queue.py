import pytest


pytestmark = pytest.mark.unit


def test_default_redis_url_targets_redis_service_name(monkeypatch):
    from indexing import queue

    monkeypatch.delenv("REDIS_URL", raising=False)

    assert queue._redis_url() == "redis://redis:6379/0"
