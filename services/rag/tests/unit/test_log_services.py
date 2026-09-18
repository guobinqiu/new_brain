import asyncio
from types import SimpleNamespace

import pytest
from shared.config import LoggingConfig


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("endpoint", ["logs", "labels", "traces"])
def test_log_queries_are_unavailable_without_loki(endpoint):
    from fastapi import HTTPException
    from services.rag.core.api.services import logs, traces

    state = SimpleNamespace(config=SimpleNamespace(logging=LoggingConfig(loki_url=None)))
    calls = {
        "logs": lambda: logs.logs(state),
        "labels": lambda: logs.log_label_values(state, "container", None),
        "traces": lambda: traces.traces(state),
    }
    with pytest.raises(HTTPException) as exc:
        asyncio.run(calls[endpoint]())
    assert exc.value.status_code == 503
    assert exc.value.detail == "log storage is not configured"


def test_logs_query_forward_and_returns_next_start(monkeypatch):
    from services.rag.core.api.services import logs as service

    captured = {}

    async def fake_query_range(loki_url, query, start, end, limit, direction):
        assert loki_url == "http://logs:3100"
        captured.update({"query": query, "start": start, "end": end, "limit": limit, "direction": direction})
        return [
            {"stream": {"container": "rag"}, "values": [
                ["1000000000", "old"],
                ["2000000000", "new"],
            ]},
        ]

    monkeypatch.setattr(service, "query_range", fake_query_range)

    state = SimpleNamespace(config=SimpleNamespace(logging=LoggingConfig(loki_url="http://logs:3100")))
    result = asyncio.run(service.logs(state, container="rag", start="1000", end="2000", limit=2))

    assert captured["direction"] == "forward"
    assert [row["line"] for row in result["logs"]] == ["old", "new"]
    assert result["next_start"] == "2000000001"


def test_traces_query_forward_and_returns_next_start(monkeypatch):
    from services.rag.core.api.services import traces as service

    captured = {}

    async def fake_query_range(loki_url, query, start, end, limit, direction):
        assert loki_url == "http://logs:3100"
        captured.update({"query": query, "start": start, "end": end, "limit": limit, "direction": direction})
        return [
            {"values": [
                ["1000000000", '{"event":"search_trace","app_id":"imsdom","query":"old"}'],
                ["2000000000", '{"event":"search_trace","app_id":"imsdom","query":"new"}'],
            ]},
        ]

    monkeypatch.setattr(service, "query_range", fake_query_range)

    state = SimpleNamespace(config=SimpleNamespace(logging=LoggingConfig(loki_url="http://logs:3100")))
    result = asyncio.run(service.traces(state, app_id="imsdom", start="1000", end="2000", limit=2))

    assert captured["direction"] == "forward"
    assert [row["query"] for row in result["traces"]] == ["old", "new"]
    assert result["next_start"] == "2000000001"
