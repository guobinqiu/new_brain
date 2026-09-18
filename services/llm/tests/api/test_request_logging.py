import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from services.llm.src.api.middleware import logging as middleware


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path, logged", [("/ready", False), ("/api/v1/llm/chat/stream", True)])
async def test_request_timing_skips_ready_only(monkeypatch, path, logged):
    calls = []
    monkeypatch.setattr(middleware, "log_perf", lambda *args, **kwargs: calls.append(kwargs))
    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})

    async def next_handler(request):
        return JSONResponse({"status": "ready"})

    response = await middleware.log_requests(request, next_handler)
    assert response.status_code == 200
    assert response.headers["X-Trace-Id"]
    assert bool(calls) is logged
