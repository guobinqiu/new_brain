"""Chat 路由单测（§11.1）。

覆盖：
- TestClient 流式：POST /api/open/llm/chat/stream 返回 text/event-stream，
  收到 SSE 事件 token/done
- Cache-Control / Connection / X-Accel-Buffering 头
"""

from __future__ import annotations

import json
import time

import pytest

from auth import AppCredential, sign_request


def _try_load_app():
    """装配一个测试用 FastAPI app。"""
    try:
        from main import app  # type: ignore
        return app
    except Exception:  # noqa: S110 — 多路径 monkeypatch 探测，模块无目标属性是预期
        pass
    # 退化：手动装配
    try:
        from fastapi import FastAPI

        from llm.src.api.routes.chat import router as chat_router  # type: ignore
    except Exception as exc:
        pytest.fail(f"Chat app not importable — RED ({exc})")
    app = FastAPI()
    app.include_router(chat_router)
    return app


@pytest.fixture
def client(monkeypatch):
    try:
        from fastapi.testclient import TestClient
    except ImportError as exc:
        pytest.fail(f"fastapi.testclient not importable (expected installed): {exc}")

    async def _get_app(app_id: str):
        return AppCredential(app_id=app_id, access_key="test_access", secret_key="test_secret")

    monkeypatch.setattr("api.auth._get_app", _get_app)
    return TestClient(_try_load_app())


def _chat_request_body(message: str = "hi", thread_id: str = "t1") -> dict:
    return {"thread_id": thread_id, "message": message}


def _signed_chat_request(message: str = "hi", thread_id: str = "t1") -> tuple[bytes, dict]:
    body = _chat_request_body(message, thread_id)
    body_bytes = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "X-App-Id": "test_app",
        "X-Access-Key": "test_access",
        "X-Timestamp": str(ts),
        "X-Signature": sign_request(
            "test_secret",
            "POST",
            "/api/open/llm/chat/stream",
            str(ts),
            body_bytes,
            "test_app",
        ),
    }
    return body_bytes, headers


# ────────────────────────── 流式 /api/open/llm/chat/stream ──────────────────────────


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


def test_chat_stream_returns_event_stream_content_type(monkeypatch, client):
    """POST /api/open/llm/chat/stream 必须返回 text/event-stream content type。"""

    class _Graph:
        async def astream(self, *a, **kw):
            if False:
                yield ("values", {})

    async def _get_graph(*a, **k):
        return _Graph()

    for module_name in ("agent.registry", "api.routes.chat"):
        try:
            monkeypatch.setattr(f"{module_name}.get_graph", _get_graph)
        except Exception:  # noqa: S110 — 多路径 monkeypatch 探测，模块无目标属性是预期
            pass

    body, headers = _signed_chat_request("hi")
    with client.stream("POST", "/api/open/llm/chat/stream", content=body, headers=headers) as resp:
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        # accept either exact "text/event-stream" or "text/event-stream; charset=utf-8"
        assert ct.startswith("text/event-stream"), f"unexpected content-type: {ct}"


def test_chat_stream_sets_required_sse_headers(monkeypatch, client):
    """SSE 响应头必须含 Cache-Control/Connection/X-Accel-Buffering。"""

    class _Graph:
        async def astream(self, *a, **kw):
            if False:
                yield ("values", {})

    async def _get_graph(*a, **k):
        return _Graph()

    for module_name in ("agent.registry", "api.routes.chat"):
        try:
            monkeypatch.setattr(f"{module_name}.get_graph", _get_graph)
        except Exception:  # noqa: S110 — 多路径 monkeypatch 探测，模块无目标属性是预期
            pass

    body, headers = _signed_chat_request("hi")
    with client.stream("POST", "/api/open/llm/chat/stream", content=body, headers=headers) as resp:
        assert resp.status_code == 200
        headers = resp.headers
        assert "no-cache" in headers.get("Cache-Control", "").lower()
        assert headers.get("Connection", "").lower() == "keep-alive"
        assert headers.get("X-Accel-Buffering") == "no"


def test_chat_stream_emits_token_done_events(monkeypatch, client):
    """端到端 SSE：graph 应推 token* → done 序列。"""

    from langchain_core.messages import AIMessage

    written: list = []
    final_state = {"messages": [AIMessage(content="综合回复：退款 7 天")]}

    class _Graph:
        async def astream(self, input_data, config=None, stream_mode=None):
            # mode == "custom" → 推 writer
            # mode == "values"  → 推 final state
            # 我们用 stream_mode=["custom","values"] 双模

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

    async def _get_graph(*a, **k):
        return _Graph()

    for module_name in ("agent.registry", "api.routes.chat"):
        try:
            monkeypatch.setattr(f"{module_name}.get_graph", _get_graph)
        except Exception:  # noqa: S110 — 多路径 monkeypatch 探测，模块无目标属性是预期
            pass

    raw = ""
    body, headers = _signed_chat_request("refund?")
    with client.stream("POST", "/api/open/llm/chat/stream", content=body, headers=headers) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            raw += chunk

    events = _parse_sse(raw)
    types = [e.get("type") for e in events]

    assert "token" in types, f"SSE 事件中应含 token，实际 type 序列: {types}"
    assert "done" in types
    assert types[-1] == "done"


def test_chat_stream_handles_error_emits_error_event(monkeypatch, client):
    """graph 抛异常时，SSE 应推 error 事件而不是返回 5xx。"""

    class _FailGraph:
        async def astream(self, *a, **kw):
            raise RuntimeError("upstream broken")
            yield  # for type checker

    async def _get_graph(*a, **k):
        return _FailGraph()

    for module_name in ("agent.registry", "api.routes.chat"):
        try:
            monkeypatch.setattr(f"{module_name}.get_graph", _get_graph)
        except Exception:  # noqa: S110 — 多路径 monkeypatch 探测，模块无目标属性是预期
            pass

    raw = ""
    body, headers = _signed_chat_request("hi")
    with client.stream("POST", "/api/open/llm/chat/stream", content=body, headers=headers) as resp:
        assert resp.status_code == 200  # SSE 业务错误保持 200
        for chunk in resp.iter_text():
            raw += chunk

    events = _parse_sse(raw)
    types = [e.get("type") for e in events]
    assert "error" in types, f"应推 error 事件，实际: {types}"
    err = next(e for e in events if e.get("type") == "error")
    assert "message" in err or "trace_id" in err



def test_chat_route_module_path():
    """chat 路由必须位于 api.routes.chat 且包含 /api/open/llm/chat/stream 端点。"""
    try:
        from llm.src.api.routes.chat import router  # type: ignore
    except ImportError as exc:
        pytest.fail(f"api.routes.chat.router 缺失: {exc}")
    paths = sorted({getattr(r, "path", "") for r in router.routes})
    assert "/api/open/llm/chat/stream" in paths, (
        f"router 中必须含 /api/open/llm/chat/stream（架构 §6.1 SSE 端点要求），当前: {paths}"
    )
