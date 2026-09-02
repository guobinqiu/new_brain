import asyncio

import httpx
import pytest


pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers=None):
        self.requests.append({"url": url, "headers": headers or {}})
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def test_parse_peers_trims_empty_items():
    from rag.nodes import parse_peers

    assert parse_peers(" http://a:8000, ,http://b:8000,") == ["http://a:8000", "http://b:8000"]
    assert parse_peers("") == []
    assert parse_peers(None) == []


def test_fetch_peers_returns_success_and_forwards_authorization():
    from rag.nodes import fetch_peers

    async def _run():
        client = FakeAsyncClient(
            {
                "http://a:8000/api/open/rag/monitor": FakeResponse(200, {"node_id": "node-a", "ready": True}),
                "http://b:8000/api/open/rag/monitor": FakeResponse(200, {"ready": True}),
            }
        )

        rows = await fetch_peers(["http://a:8000", "http://b:8000"], "/api/open/rag/monitor", "Bearer token", client=client)

        assert [row.node_id for row in rows] == ["node-a", "b:8000"]
        assert [row.status for row in rows] == ["ok", "ok"]
        assert rows[0].data == {"node_id": "node-a", "ready": True}
        assert client.requests[0]["headers"]["Authorization"] == "Bearer token"

    asyncio.run(_run())


def test_fetch_peers_keeps_failed_peer_as_unreachable():
    from rag.nodes import fetch_peers

    async def _run():
        client = FakeAsyncClient(
            {
                "http://a:8000/api/open/rag/config": FakeResponse(500, {"error": "failed"}),
                "http://b:8000/api/open/rag/config": httpx.ConnectTimeout("timeout"),
            }
        )

        rows = await fetch_peers(["http://a:8000", "http://b:8000"], "/api/open/rag/config", None, client=client)

        assert [row.node_id for row in rows] == ["a:8000", "b:8000"]
        assert [row.status for row in rows] == ["unreachable", "unreachable"]
        assert rows[0].data is None
        assert "status 500" in rows[0].error
        assert "timeout" in rows[1].error

    asyncio.run(_run())


def test_local_result_uses_env_node_id(monkeypatch):
    from rag.nodes import local_result

    monkeypatch.setenv("RAG_NODE_ID", "node-local")

    row = local_result({"ready": True})

    assert row.node_id == "node-local"
    assert row.base_url == "local"
    assert row.status == "ok"
    assert row.data == {"ready": True}
