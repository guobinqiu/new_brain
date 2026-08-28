"""RagClient 单测（§11.1）。

覆盖：
- 请求 headers 4 个齐全（X-App-Id / X-Access-Key / X-Timestamp / X-Signature）
- content=body_bytes 字节级一致（不重序列化）
- 5xx 自动重试 N 次
- 401/403 不重试
- TimeoutException 重试
- RagClient.aclose() 释放
"""

from __future__ import annotations

import json

import httpx
import pytest

# ──────────────────────────── helpers ────────────────────────────


def _build_request(**client_kwargs):
    """Skip helper when RagClient / SearchRequest not implemented."""
    try:
        from llm.src.rag.client import RagClient  # type: ignore
        from llm.src.rag.schemas import SearchRequest  # type: ignore
    except Exception as exc:
        pytest.fail(f"rag.client / rag.schemas not implemented — RED ({exc})")
    return RagClient(**client_kwargs), SearchRequest


# ──────────────────────────── header / body bytes ────────────────────────────


@pytest.mark.asyncio
async def test_client_sends_all_four_signature_headers(install_mock_transport):
    """所有 4 个 X-* 头必须在请求中。"""
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local:8000",
        app_id="my_app",
        access_key="AKIDEXAMPLE",
        secret="my_secret",
    )
    try:
        await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert len(captured) == 1
    headers = captured[0].headers
    assert headers.get("X-App-Id") == "my_app"
    assert headers.get("X-Access-Key") == "AKIDEXAMPLE"
    assert "X-Timestamp" in headers
    assert headers.get("X-Timestamp").isdigit()
    assert "X-Signature" in headers
    assert len(headers.get("X-Signature")) == 64
    assert headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
async def test_client_sends_exact_body_bytes_no_reserialize(install_mock_transport):
    """HTTP body 字节必须与签名对象的 body_bytes 完全一致（不让 httpx 重序列化）。"""
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="my_app",
        access_key="AK",
        secret="secret",
    )
    try:
        req = SearchRequest(query="退款流程", top_k=3, mode="hybrid")
        await client.search(req)
    finally:
        await client.aclose()

    # 紧凑 JSON 序列化：与客户端内部使用的字节级一致
    expected_bytes = json.dumps(
        req.model_dump(exclude_none=True),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    # 但实现可能使用 ensure_ascii=True + 写 utf-8，二者解码后内容相同
    # — 这里我们断言：服务端收到的 body（解码后）与字段集合一致
    sent = captured[0].content
    # 字节级相等（最严格）
    assert sent == expected_bytes, (
        "body 被 httpx 重新序列化，破坏了紧凑 JSON 字节级不变量。"
        f"\n  客户端: {sent!r}\n  期望字节: {expected_bytes!r}"
    )


@pytest.mark.asyncio
async def test_client_signature_header_matches_sign_function(install_mock_transport):
    """X-Signature 的值必须等于 sign(body_bytes, ...) 的输出。"""
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    try:
        from llm.src.rag.client import sign  # type: ignore
        from llm.src.rag.schemas import SearchRequest  # type: ignore
    except Exception as exc:
        pytest.fail(f"rag.client / rag.schemas not implemented — RED ({exc})")

    client, _ = _build_request(
        base_url="http://rag.local",
        app_id="agent_1",
        access_key="AK",
        secret="mySecret",
    )
    try:
        req = SearchRequest(query="hi", top_k=5)
        await client.search(req)
    finally:
        await client.aclose()

    sent_req = captured[0]
    # 真实 X-Timestamp 来自客户端时钟；我们重算期望签名
    ts = int(sent_req.headers["X-Timestamp"])
    expected_sig = sign(
        sent_req.content,
        method="POST",
        path="/api/open/search",
        ts=ts,
        app_id="agent_1",
        secret="mySecret",
    )
    assert sent_req.headers["X-Signature"] == expected_sig


@pytest.mark.asyncio
async def test_client_url_is_base_url_plus_search_path(install_mock_transport):
    """URL 必须是 base_url + '/api/open/search'，不拼 query。"""
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local:8000/",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    url = str(captured[0].url)
    assert url.endswith("/api/open/search")
    # base_url 尾部斜杠应被 rstrip
    assert "rag.local:8000/api/open/search" in url


# ──────────────────────────── 重试策略 ────────────────────────────


@pytest.mark.asyncio
async def test_client_retries_on_5xx(install_mock_transport):
    """5xx 响应触发重试，最终失败但应尝试 max_attempts 次。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="upstream unavailable")

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
        max_retries=2,  # 额外重试次数（含初次 = 总 max_attempts=3?），具体看实现
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    # 必须有 ≥1 次初始尝试 + 至少 1 次重试
    assert call_count["n"] >= 2, f"5xx 应被重试，实际只调了 {call_count['n']} 次"
    # 结果应是失败
    assert result.success is False
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_client_does_not_retry_on_401(install_mock_transport):
    """401（签名失败）不应重试 —— 换时间戳也不会改变结果。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, text="invalid signature")

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert call_count["n"] == 1, f"401 不应重试，实际调了 {call_count['n']} 次"
    assert result.success is False
    assert result.status_code == 401


@pytest.mark.asyncio
async def test_client_does_not_retry_on_403(install_mock_transport):
    """403 也不重试（认证错误）。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(403, text="forbidden")

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert call_count["n"] == 1
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_client_does_not_retry_on_422(install_mock_transport):
    """422（业务校验失败）不应重试。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(422, text="invalid query")

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert call_count["n"] == 1
    assert result.status_code == 422


@pytest.mark.asyncio
async def test_client_retries_on_timeout(install_mock_transport):
    """httpx.TimeoutException 应被 rag_retry 捕获并重试。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.ConnectTimeout("simulated timeout")
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert call_count["n"] == 2, f"超时后重试，最终成功；应调 {call_count['n']} 次"
    assert result.success is True


@pytest.mark.asyncio
async def test_client_retries_on_connect_error(install_mock_transport):
    """httpx.ConnectError 也应被重试。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert call_count["n"] == 2
    assert result.success is True


@pytest.mark.asyncio
async def test_client_5xx_then_recovery_succeeds(install_mock_transport):
    """5xx 重试 → 中途成功 → 终态 success=True。"""
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(500, text="oops")
        if call_count["n"] == 2:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "c1",
                        "content": "found",
                    }
                ],
                "elapsed_ms": 5.0,
            },
        )

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert result.success is True
    assert call_count["n"] >= 3  # 至少重试了 2 次
    assert len(result.documents) == 1
    assert result.documents[0].id == "c1"


# ──────────────────────────── 客户端生命周期 ────────────────────────────


@pytest.mark.asyncio
async def test_client_aclose_releases_resources():
    """aclose() 必须关闭内部 AsyncClient —— 重复 aclose 不抛错。"""
    try:
        from llm.src.rag.client import RagClient  # type: ignore
    except Exception as exc:
        pytest.fail(f"rag.client not implemented — RED ({exc})")

    client = RagClient(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    await client.aclose()
    # 第二次 aclose 不应抛
    await client.aclose()


@pytest.mark.asyncio
async def test_get_rag_client_singleton_returns_same_instance():
    """get_rag_client() 是模块级单例 —— 两次调用返回同一实例（无重新构造）。"""
    try:
        from llm.src.rag.client import get_rag_client  # type: ignore
    except Exception as exc:
        pytest.fail(f"get_rag_client not implemented — RED ({exc})")

    a = get_rag_client()
    b = get_rag_client()
    assert a is b
    # 应当有 aclose 方法以便 lifespan 关闭
    assert hasattr(a, "aclose") and callable(a.aclose)


@pytest.mark.asyncio
async def test_result_documents_parsed_as_pydantic(install_mock_transport):
    """成功响应中的 results[] 应被解析为 Document 对象。"""
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "chunk-99",
                        "content": "退 7 天",
                    }
                ],
                "elapsed_ms": 3.5,
            },
        )

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert result.success is True
    assert result.status_code == 200
    assert result.elapsed_ms == 3.5
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.id == "chunk-99"


@pytest.mark.asyncio
async def test_result_documents_parse_simplified_qdrant_api_response(install_mock_transport):
    """真实 qdrant `/api/open/search` 返回简化 result 时不应被跳过。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "doc-1",
                        "content": "命中的 chunk 文本",
                        "score": 0.82,
                    }
                ],
                "elapsed_ms": 271.7,
            },
        )

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local",
        app_id="a",
        access_key="k",
        secret="s",
    )
    try:
        result = await client.search(SearchRequest(query="hi"))
    finally:
        await client.aclose()

    assert result.success is True
    assert result.elapsed_ms == 271.7
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.id == "doc-1"
    assert doc.content == "命中的 chunk 文本"
