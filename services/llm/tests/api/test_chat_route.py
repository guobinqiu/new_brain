"""Chat 路由单测（§11.1）。

覆盖：
- 直接调用 chat_stream 并迭代 StreamingResponse，返回 text/event-stream，
  收到 SSE 事件 token/done
- Cache-Control / Connection / X-Accel-Buffering 头
"""

from __future__ import annotations

import json

import httpx
import pytest
from openai import APITimeoutError
from shared.upstream import UpstreamServiceError

from starlette.requests import Request

from services.llm.src.api.routes.chat import ChatRequest, chat_stream


pytestmark = pytest.mark.unit


@pytest.fixture
def route_request(monkeypatch):
    from services.llm.src.api.middleware import limiter

    monkeypatch.setattr(limiter, "enabled", False)
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/llm/chat/stream",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    })


# ────────────────────────── 流式 /api/v1/llm/chat/stream ──────────────────────────


def _parse_sse(raw: str) -> list:
    """解析 SSE 流 → list[dict]."""
    events: list = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    # 不可解析时记原始串
                    events.append({"_raw": payload})
    return events


async def test_chat_stream_returns_event_stream_content_type(route_request):
    """chat_stream 必须返回 text/event-stream content type。"""

    class _Graph:
        async def astream(self, *a, **kw):
            if False:
                yield ("values", {})

    resp = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1"), graph=_Graph())
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert ct.startswith("text/event-stream"), f"unexpected content-type: {ct}"


async def test_chat_stream_sets_required_sse_headers(route_request):
    """SSE 响应头必须含 Cache-Control/Connection/X-Accel-Buffering。"""

    class _Graph:
        async def astream(self, *a, **kw):
            if False:
                yield ("values", {})

    resp = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1"), graph=_Graph())
    assert resp.status_code == 200
    headers = resp.headers
    assert "no-cache" in headers.get("Cache-Control", "").lower()
    assert headers.get("Connection", "").lower() == "keep-alive"
    assert headers.get("X-Accel-Buffering") == "no"


async def test_chat_stream_emits_token_done_events(route_request, monkeypatch):
    """SSE 序列化单测：graph 应推 token* → done 序列。"""

    from langchain_core.messages import AIMessage
    from langsmith import get_tracing_context
    from services.llm.src.config import settings

    monkeypatch.setattr(settings, "langchain_tracing_v2", False)
    monkeypatch.setattr(settings, "langchain_project", "yaml-project")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_PROJECT", "ignored-project")

    written: list = []
    final_state = {"messages": [AIMessage(content="综合回复：退款 7 天")]}

    class _Graph:
        async def astream(self, input_data, config=None, stream_mode=None):
            context = get_tracing_context()
            assert context["enabled"] is False
            assert context["project_name"] == "yaml-project"
            assert input_data["messages"][0].content == "refund?"
            assert config == {"configurable": {"thread_id": "t1"}}
            assert stream_mode == ["custom"]

            async def _producer():
                for chunk in ["退款", " ", "7", " 天"]:
                    yield ("custom", {"type": "token", "content": chunk})
                yield ("values", final_state)

            async for ev in _producer():
                mode, payload = ev
                if stream_mode and not (
                    mode in stream_mode
                    or (isinstance(stream_mode, list) and mode in stream_mode)
                ):
                    continue
                yield (mode, payload)
                # 记录
                if mode == "custom":
                    written.append(payload)

    resp = await chat_stream(route_request, ChatRequest(message="refund?", thread_id="t1"), graph=_Graph())
    assert resp.status_code == 200
    raw = "".join([chunk async for chunk in resp.body_iterator])

    events = _parse_sse(raw)
    types = [e.get("type") for e in events]

    assert "token" in types, f"SSE 事件中应含 token，实际 type 序列: {types}"
    assert "done" in types
    assert types[-1] == "done"
    assert events == [*written, {"type": "done"}]
    assert "".join(event["content"] for event in events if event["type"] == "token") == "退款 7 天"


@pytest.mark.parametrize("error,service", [
    (RuntimeError("upstream broken"), "llm"),
    (APITimeoutError(request=httpx.Request("POST", "https://model.test")), "llm"),
    (UpstreamServiceError(service="rag", error="search failed", retryable=True, status_code=503), "rag"),
])
async def test_chat_stream_handles_error_emits_error_event(route_request, monkeypatch, error, service):
    """graph 抛异常时，SSE 应推 error 事件而不是返回 5xx。"""

    import langsmith
    from services.llm.src.api.routes import chat
    from services.llm.src.config import settings

    monkeypatch.setattr(settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(settings, "langchain_project", "yaml-project")
    monkeypatch.setattr(settings, "langchain_api_key", "test-tracing-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_PROJECT", "ignored-project")
    client = object()
    client_options = []

    def make_client(**kwargs):
        client_options.append(kwargs)
        return client

    monkeypatch.setattr(langsmith, "Client", make_client)
    monkeypatch.setattr(chat, "_get_tracing_client", chat._get_tracing_client.__wrapped__)
    original_context = langsmith.get_tracing_context()
    observed = []

    class _FailGraph:
        async def astream(self, *a, **kw):
            observed.append(langsmith.get_tracing_context())
            raise error
            yield  # for type checker

    resp = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1"), graph=_FailGraph())
    assert resp.status_code == 200  # SSE 业务错误保持 200
    raw = "".join([chunk async for chunk in resp.body_iterator])

    events = _parse_sse(raw)
    types = [e.get("type") for e in events]
    assert "error" in types, f"应推 error 事件，实际: {types}"
    err = next(e for e in events if e.get("type") == "error")
    assert "message" in err or "trace_id" in err
    assert err["message"] == str(error)
    assert err["service"] == service
    assert types == ["error"]
    assert observed[0]["enabled"] is True
    assert observed[0]["project_name"] == "yaml-project"
    assert observed[0]["client"] is client
    assert client_options == [{"api_key": "test-tracing-key"}]
    assert langsmith.get_tracing_context() == original_context



def test_chat_route_module_path():
    """chat 路由必须位于 api.routes.chat 且包含 /api/v1/llm/chat/stream 端点。"""
    try:
        from services.llm.src.api.routes.chat import router  # type: ignore
    except ImportError as exc:
        pytest.fail(f"api.routes.chat.router 缺失: {exc}")
    paths = sorted({getattr(r, "path", "") for r in router.routes})
    assert "/api/v1/llm/chat/stream" in paths, (
        f"router 中必须含 /api/v1/llm/chat/stream（架构 §6.1 SSE 端点要求），当前: {paths}"
    )
