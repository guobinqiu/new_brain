from dataclasses import replace

import pytest
from pydantic import ValidationError

from rag.api.runtime import runtime
from rag.api.schemas import DebugEncodeRequest, DebugSearchRequest
from rag.api.services import search as service
from rag.auth import Principal


pytestmark = pytest.mark.unit


class DebugDense:
    ready = True

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class DebugSparse:
    ready = True

    def supports_sparse_vector(self):
        return True

    def embed_query(self, text):
        return {"9": 0.9, "3": 0.3}


class DebugStore:
    ready = True

    def __init__(self):
        self.calls = []

    def app_collection_exists(self, app_id):
        return True

    def app_context(self, app_id):
        from contextlib import nullcontext

        self.calls.append(("app_context", app_id))
        return nullcontext()

    def build_file_filter(self, file_ids=None):
        self.calls.append(("build_file_filter", tuple(file_ids or [])))
        return ("file-filter", tuple(file_ids or []))

    def search_dense(self, query, limit, metadata_filter):
        self.calls.append(("search_dense", query, limit, metadata_filter))
        return [
            {
                "id": "dense-1",
                "content": "dense content",
                "metadata": {"file_id": "file-a", "chunk_index": 1},
                "_score": 0.8,
            }
        ]

    def search_sparse(self, query, limit, metadata_filter):
        self.calls.append(("search_sparse", query, limit, metadata_filter))
        return [
            {
                "id": "sparse-1",
                "content": "sparse content",
                "metadata": {"file_id": "file-a", "chunk_index": 2},
                "_score": 0.9,
            }
        ]


def _set_application(monkeypatch, *, sparse=None, store=None):
    config = replace(runtime.application.config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = sparse
            self.store = store or DebugStore()

    application = Application()
    monkeypatch.setattr(runtime, "application", application)
    return application


def test_debug_dense_search_encodes_query_and_searches_dense(monkeypatch):
    store = DebugStore()
    _set_application(monkeypatch, sparse=DebugSparse(), store=store)

    body = service.debug_dense_search(
        "tenant_a",
        DebugSearchRequest(query="表见代理", top_k=3, file_ids=["file-a"]),
        Principal(type="admin", app_id=""),
    )

    assert body["type"] == "dense"
    assert body["query_vector"] == [0.1, 0.2, 0.3]
    assert body["results"][0]["id"] == "dense-1"
    assert store.calls == [
        ("build_file_filter", ("file-a",)),
        ("app_context", "tenant_a"),
        ("search_dense", "表见代理", 3, ("file-filter", ("file-a",))),
    ]


def test_debug_sparse_search_encodes_query_and_searches_sparse(monkeypatch):
    store = DebugStore()
    _set_application(monkeypatch, sparse=DebugSparse(), store=store)

    body = service.debug_sparse_search(
        "tenant_a",
        DebugSearchRequest(query="表见代理", top_k=3),
        Principal(type="admin", app_id=""),
    )

    assert body["type"] == "sparse"
    assert body["query_vector"] == {"indices": [3, 9], "values": [0.3, 0.9]}
    assert body["results"][0]["id"] == "sparse-1"
    assert store.calls == [
        ("build_file_filter", ()),
        ("app_context", "tenant_a"),
        ("search_sparse", "表见代理", 3, ("file-filter", ())),
    ]


def test_debug_dense_encode_only_encodes_query(monkeypatch):
    application = _set_application(monkeypatch)

    body = service.debug_dense_encode(
        "tenant_a",
        DebugEncodeRequest(query="表见代理"),
        Principal(type="admin", app_id=""),
    )

    assert body == {
        "type": "dense",
        "query": "表见代理",
        "query_vector": [0.1, 0.2, 0.3],
    }
    assert application.store.calls == []


def test_debug_sparse_encode_returns_400_when_sparse_disabled(monkeypatch):
    from fastapi import HTTPException

    _set_application(monkeypatch, sparse=None)

    with pytest.raises(HTTPException) as exc:
        service.debug_sparse_encode(
            "tenant_a",
            DebugEncodeRequest(query="表见代理"),
            Principal(type="admin", app_id=""),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "sparse is not enabled"


def test_debug_search_accepts_top_k_up_to_100(monkeypatch):
    store = DebugStore()
    _set_application(monkeypatch, store=store)

    service.debug_dense_search(
        "tenant_a",
        DebugSearchRequest(query="表见代理", top_k=100),
        Principal(type="admin", app_id=""),
    )

    assert store.calls[-1] == ("search_dense", "表见代理", 100, ("file-filter", ()))


def test_debug_search_rejects_top_k_over_100():
    with pytest.raises(ValidationError):
        DebugSearchRequest(query="表见代理", top_k=101)
