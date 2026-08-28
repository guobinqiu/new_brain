import asyncio

import pytest


pytestmark = pytest.mark.unit


def test_logs_query_forward_and_returns_next_start(monkeypatch):
    from rag.api.services import logs as service

    captured = {}

    async def fake_query_range(query, start, end, limit, direction):
        captured.update({"query": query, "start": start, "end": end, "limit": limit, "direction": direction})
        return [
            {"stream": {"container": "rag-api"}, "values": [
                ["1000000000", "old"],
                ["2000000000", "new"],
            ]},
        ]

    monkeypatch.setattr(service, "query_range", fake_query_range)

    result = asyncio.run(service.logs(container="rag-api", start="1000", end="2000", limit=2))

    assert captured["direction"] == "forward"
    assert [row["line"] for row in result["logs"]] == ["old", "new"]
    assert result["next_start"] == "2000000001"


def test_traces_query_forward_and_returns_next_start(monkeypatch):
    from rag.api.services import traces as service

    captured = {}

    async def fake_query_range(query, start, end, limit, direction):
        captured.update({"query": query, "start": start, "end": end, "limit": limit, "direction": direction})
        return [
            {"values": [
                ["1000000000", '{"event":"search_trace","app_id":"imsdom","query":"old"}'],
                ["2000000000", '{"event":"search_trace","app_id":"imsdom","query":"new"}'],
            ]},
        ]

    monkeypatch.setattr(service, "query_range", fake_query_range)

    result = asyncio.run(service.traces(app_id="imsdom", start="1000", end="2000", limit=2))

    assert captured["direction"] == "forward"
    assert [row["query"] for row in result["traces"]] == ["old", "new"]
    assert result["next_start"] == "2000000001"
