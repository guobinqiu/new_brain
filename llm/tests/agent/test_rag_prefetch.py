"""RAG 预检索节点单测。

覆盖：
- rag_prefetch_node 正确调用 client.search
- 失败路径返回空 rag_context
- 无 HumanMessage 返回空 rag_context
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_rag_prefetch_calls_client_with_query(monkeypatch):
    """rag_prefetch_node 用最后一条 HumanMessage 的内容调 client.search。"""
    from langchain_core.messages import HumanMessage

    from llm.src.agent.nodes.rag_prefetch import rag_prefetch_node

    captured = {}

    class _C:
        async def aclose(self): pass
        async def search(self, req, **kwargs):
            captured["query"] = req.query
            from llm.src.rag.schemas import Document
            return type("R", (), {
                "success": True, "status_code": 200,
                "documents": [
                    Document(
                        id="d1",
                        content="测试内容",
                    )
                ],
                "elapsed_ms": 1.0, "raw": {}, "error": "",
            })()

    monkeypatch.setattr("llm.src.rag.client.get_rag_client", lambda: _C())

    from llm.src.api.auth import AppCredential
    import llm.src.api.auth as auth_mod

    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="imsdom", access_key="ak", secret_key="sk"),
    )

    state = {"messages": [HumanMessage(content="怎么退款？")]}
    result = await rag_prefetch_node(state)
    assert captured["query"] == "怎么退款？"
    assert "测试内容" in result["rag_context"]


@pytest.mark.asyncio
async def test_rag_prefetch_empty_on_exception(monkeypatch):
    """client.search 抛异常时返回空 rag_context。"""
    from langchain_core.messages import HumanMessage

    from llm.src.agent.nodes.rag_prefetch import rag_prefetch_node

    class _BadClient:
        async def aclose(self): pass
        async def search(self, req, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("llm.src.rag.client.get_rag_client", lambda: _BadClient())

    from llm.src.api.auth import AppCredential
    import llm.src.api.auth as auth_mod

    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="imsdom", access_key="ak", secret_key="sk"),
    )

    state = {"messages": [HumanMessage(content="hi")]}
    result = await rag_prefetch_node(state)
    assert result["rag_context"] == ""


@pytest.mark.asyncio
async def test_rag_prefetch_empty_on_no_human_message():
    """没有 HumanMessage 时返回空 rag_context。"""
    from langchain_core.messages import AIMessage

    from llm.src.agent.nodes.rag_prefetch import rag_prefetch_node

    state = {"messages": [AIMessage(content="hi")]}
    result = await rag_prefetch_node(state)
    assert result["rag_context"] == ""
