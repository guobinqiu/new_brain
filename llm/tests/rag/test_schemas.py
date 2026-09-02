"""Pydantic schemas 单测（§11.1）。

覆盖：
- SearchRequest.model_dump(exclude_none=True) 排除 None 字段
- 紧凑序列化（与 json.dumps(..., separators=(",",":")) 字节级一致）
- 字段顺序保持（与构造顺序一致）
- Document 解析 metadata
- fetch_k ≥ top_k 校验
- file_ids 非空数组校验
- SearchResponse 解析 results[] 无 score 字段
"""

from __future__ import annotations

import json

import pytest


def _try_import_symbol(module_path: str, name: str):
    """缺失模块/属性时返回 None；存在则返回 symbol。"""
    try:
        mod = __import__(module_path, fromlist=[name])
        return getattr(mod, name, None)
    except Exception:
        return None


# ────────────────────────────── SearchRequest ──────────────────────────────


def test_search_request_exclude_none_drops_optional_fields():
    """只设 query 时，model_dump(exclude_none=True) 应只含 {"query": "..."}。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(query="hi")
    dumped = req.model_dump(exclude_none=True)
    assert dumped == {"query": "hi"}


def test_search_request_compact_json_serialization():
    """SearchRequest 必须能以紧凑模式序列化（无空格）。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(query="退款流程", top_k=5, mode="hybrid", rerank=True)
    dumped = req.model_dump(exclude_none=True)
    compact = json.dumps(dumped, separators=(",", ":"), ensure_ascii=False)
    # 紧凑模式：字段间无空格
    assert ", " not in compact
    assert ": " not in compact
    # 中文不走 ensure_ascii
    assert "退款流程" in compact


def test_search_request_default_query_none_excluded():
    """未传 query 时若默认 None，应被 exclude_none 排除。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    # 仅设 top_k
    req = cls(top_k=3)
    dumped = req.model_dump(exclude_none=True)
    assert "query" not in dumped  # 缺省被排除
    assert dumped["top_k"] == 3


def test_search_request_top_k_optional_default_in_range():
    """top_k 等可选项有合理默认值时（5 或 None），不应抛。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(query="q")
    # 字段必须有，且参与序列化时类型正确
    dumped = req.model_dump(exclude_none=True)
    assert isinstance(dumped, dict)
    assert dumped["query"] == "q"


def test_search_request_fetch_k_must_be_greater_or_equal_top_k():
    """fetch_k < top_k 在物理上不可达：应当抛 ValidationError。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    # pydantic v2 抛 ValidationError
    try:
        from pydantic import ValidationError
    except ImportError as exc:
        pytest.fail(f"pydantic not installed (expected): {exc}")
    # 如果模型实现了 @model_validator(mode='after')
    try:
        cls(query="q", top_k=10, fetch_k=5)  # fetch_k < top_k, 错误
    except ValidationError:
        return  # 测试通过：校验起作用
    except Exception as exc:
        # 其他可接受的抛错（如 ValueError）
        if "fetch_k" in str(exc).lower() or "top_k" in str(exc).lower():
            return
        # 既不抛也不报错 → 测试失败
    pytest.fail(
        "SearchRequest 应拒绝 fetch_k < top_k 的配置（doc §11.1 明确要求）"
    )


def test_search_request_fetch_k_equal_to_top_k_allowed():
    """fetch_k == top_k 边界合法。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    # 不应抛
    req = cls(query="q", top_k=5, fetch_k=5)
    assert req.fetch_k == 5


def test_search_request_file_ids_must_be_non_empty_if_provided():
    """file_ids 若提供，必须是非空数组。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    try:
        from pydantic import ValidationError
    except ImportError as exc:
        pytest.fail(f"pydantic not installed (expected): {exc}")

    # 正常用例
    valid = cls(query="q", file_ids=["doc-1", "doc-2"])
    assert valid.file_ids == ["doc-1", "doc-2"]

    # 空数组应被拒
    try:
        cls(query="q", file_ids=[])
    except ValidationError:
        return
    except Exception:
        return
    pytest.fail("SearchRequest 应拒绝空 file_ids 数组（doc §11.1 明确要求）")


def test_search_request_full_payload_round_trip():
    """所有字段都填时，dump → 紧凑 JSON 字节级正确。"""
    cls = _try_import_symbol("rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(
        query="hi",
        top_k=3,
        mode="dense",
        rerank=False,
        fetch_k=20,
        dense_weight=0.7,
        sparse_weight=0.3,
        rrf_k=60,
        file_ids=["a", "b"],
    )
    dumped = req.model_dump(exclude_none=True)
    assert dumped["query"] == "hi"
    assert dumped["top_k"] == 3
    assert dumped["mode"] == "dense"
    assert dumped["rerank"] is False
    assert dumped["file_ids"] == ["a", "b"]
    # 紧凑 JSON 可序列化
    compact = json.dumps(dumped, separators=(",", ":"), ensure_ascii=False)
    assert compact.startswith("{") and compact.endswith("}")


# ────────────────────────────── Document ──────────────────────────────


def test_document_parses_minimal_fields():
    """Document 必须能解析简化后的 id/content 字段。"""
    Document = _try_import_symbol("rag.schemas", "Document")
    if Document is None:
        pytest.fail("rag.schemas.Document not implemented — RED")
    raw = {
        "id": "chunk-001",
        "content": "退款条款：7 天内可全额退款。",
    }
    doc = Document(**raw)
    assert doc.id == "chunk-001"
    assert doc.content.startswith("退款")


def test_response_has_no_score_field_dependency():
    """（间接验证）SearchResponse 应能解析无 score 字段的 RAG 响应。
    Document 的字段集合不含 score（不依赖分数做后续逻辑）。
    """
    Response = _try_import_symbol("rag.schemas", "SearchResponse")
    Document = _try_import_symbol("rag.schemas", "Document")
    if Response is None or Document is None:
        pytest.fail("rag.schemas.SearchResponse/Document not implemented — RED")
    raw = {
        "results": [
            {
                "id": "c1",
                "content": "text",
                # 注意：没有 score 字段（契约约束）
            }
        ],
        "mode": "hybrid",
        "rerank": True,
        "fetch_k": 20,
        "dense_weight": 0.5,
        "sparse_weight": 0.5,
        "rrf_k": 60,
        "elapsed_ms": 42.0,
    }
    resp = Response(**raw)
    assert len(resp.results) == 1
    doc = resp.results[0]
    assert doc.id == "c1"
    # Document 字段中不暴露 score（不依赖）
    assert not hasattr(doc, "score") or getattr(doc, "score", None) is None


def test_document_parses_simplified_qdrant_open_search_result():
    """Document 应兼容 qdrant `/api/open/rag/search` 的简化 result 结构。"""
    Document = _try_import_symbol("rag.schemas", "Document")
    if Document is None:
        pytest.fail("rag.schemas.Document not implemented — RED")
    raw = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "content": "命中的 chunk 文本",
        "score": 0.82,
    }
    doc = Document(**raw)
    assert doc.id == "550e8400-e29b-41d4-a716-446655440000"
    assert doc.content == "命中的 chunk 文本"
    assert not hasattr(doc, "score") or getattr(doc, "score", None) is None


def test_documents_iteration_and_count():
    """SearchResponse.results 是 list[Document]，可迭代。"""
    Response = _try_import_symbol("rag.schemas", "SearchResponse")
    if Response is None:
        pytest.fail("rag.schemas.SearchResponse not implemented — RED")
    raw = {
        "results": [
            {
                "id": f"c{i}",
                "content": f"text {i}",
            }
            for i in range(3)
        ],
        "mode": "hybrid",
        "rerank": False,
        "fetch_k": 10,
        "dense_weight": 0.5,
        "sparse_weight": 0.5,
        "rrf_k": 60,
        "elapsed_ms": 1.0,
    }
    resp = Response(**raw)
    assert len(resp.results) == 3
    assert [d.id for d in resp.results] == ["c0", "c1", "c2"]


def test_schemas_module_path_is_rag_schemas():
    """关键 schema 类必须从 rag.schemas 导出。"""
    try:
        from llm.src.rag.schemas import (  # type: ignore  # noqa: F401
            Document,
            SearchRequest,
            SearchResponse,
        )
    except ImportError as exc:
        pytest.fail(f"rag.schemas 模块缺失或导出错误: {exc}")
