import json
import logging
from contextlib import nullcontext
from io import StringIO

import pytest


pytestmark = pytest.mark.unit


class ReadySparse:
    ready = True

    def search(self, query, documents, limit):
        items = []
        for document in documents:
            item = dict(document)
            item["_score"] = 1.0
            items.append(item)
        return items[:limit]


class FakeStore:
    def __init__(self, total_chunks=100):
        self.total_chunks = total_chunks
        self.calls = []

    def get_total_chunks(self, file_ids=None):
        self.calls.append(("get_total_chunks", tuple(file_ids or [])))
        return self.total_chunks

    def build_file_filter(self, file_ids=None):
        self.calls.append(("build_file_filter", tuple(file_ids or [])))
        return ("file-filter", tuple(file_ids or []))

    def app_collection_exists(self, app_id):
        self.calls.append(("app_collection_exists", app_id))
        return True

    def app_context(self, app_id):
        self.calls.append(("app_context", app_id))
        return nullcontext()

    def search_dense(self, query, limit, metadata_filter):
        self.calls.append(("search_dense", query, limit, metadata_filter))
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "_score": 0.8}]

    def search_sparse(self, query, limit, metadata_filter):
        self.calls.append(("search_sparse", query, limit, metadata_filter))
        return [{"id": "vector-sparse-1", "content": "vector sparse", "metadata": {}, "_score": 1.0}]

    def search_hybrid(self, query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k):
        self.calls.append(("search_hybrid", query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k))
        return []

    def get_search_documents(self, metadata_filter):
        self.calls.append(("get_search_documents", metadata_filter))
        return [{"id": "app-sparse-1", "content": "app sparse", "metadata": {}}]

    def sparse_uses_store(self, sparse=None):
        return False


class FakeTracedVectorStore(FakeStore):
    def encode_dense_query(self, query):
        self.calls.append(("encode_dense_query", query))
        return [0.1, 0.2, 0.3]

    def query_dense_vector(self, query_vector, limit, metadata_filter):
        self.calls.append(("query_dense_vector", query_vector, limit, metadata_filter))
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "_score": 0.8}]


class FakeVectorSparseStore(FakeStore):
    def sparse_uses_store(self, sparse=None):
        return True


class ReadyIndexedSparse:
    backend = "opensearch"
    retriever = "bm25"
    ready = True

    def start(self):
        pass

    def stop(self):
        pass

    def search_index(self, query, limit, *, app_id=None, file_ids=None):
        return [{"id": "bm25-1", "content": "bm25", "metadata": {"app_id": app_id, "file_ids": file_ids}, "_score": 2.0}]


def test_search_plan_uses_file_ids():
    import rag.search as search_mod

    plan = search_mod.SearchPlan("query", file_ids=["file_a", "file_b"])

    assert plan.file_ids == ["file_a", "file_b"]


def test_search_plan_rejects_empty_file_ids():
    import rag.search as search_mod

    with pytest.raises(ValueError, match="file_ids cannot be empty"):
        search_mod.SearchPlan("query", file_ids=[])


def test_store_backend_uses_store_backend_name_when_config_is_absent():
    from rag.search.pipeline import _store_backend

    class CustomStore:
        backend_name = "custom-store"

    assert _store_backend(CustomStore()) == "custom-store"


def test_search_plan_limits_file_ids_to_1000():
    import rag.search as search_mod

    with pytest.raises(ValueError, match="file_ids exceeds max limit: 1000"):
        search_mod.SearchPlan("query", file_ids=[f"f{i}" for i in range(1001)])


def test_search_plan_rejects_weights_greater_than_one():
    import rag.search as search_mod

    with pytest.raises(ValueError, match="search weights must be less than or equal to 1"):
        search_mod.SearchPlan("query", dense_weight=0.6, sparse_weight=0.5)


def test_executor_builds_single_chunks_pipeline_with_parallel_dense_sparse():
    import rag.search as search_mod
    from langchain_core.runnables import RunnableParallel, RunnableSequence

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="hybrid", top_k=5, file_ids=["file_a"]),
        sparse=ReadySparse(),
        store=FakeStore(),
    )

    runnable = executor._build_runnable()

    assert isinstance(runnable, RunnableSequence)
    retrieve_parallel = next(step for step in runnable.steps if isinstance(step, RunnableParallel))
    assert set(retrieve_parallel.steps__) == {"dense", "sparse"}


def test_executor_searches_single_chunks_collection_with_file_filter():
    import rag.search as search_mod

    store = FakeStore()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="hybrid", top_k=5, file_ids=["file_a"], dense_weight=0.0, sparse_weight=1.0, rrf_k=1),
        sparse=ReadySparse(),
        store=store,
    ).execute()

    assert [item["id"] for item in results] == ["app-sparse-1", "dense-1"]
    assert ("build_file_filter", ("file_a",)) in store.calls
    assert ("search_dense", "query", 5, ("file-filter", ("file_a",))) in store.calls
    assert ("get_search_documents", ("file-filter", ("file_a",))) in store.calls


def test_executor_exposes_retrieval_score():
    import rag.search as search_mod

    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="dense", top_k=1),
        store=FakeStore(),
    ).execute()

    assert results[0]["score"] == 0.8
    assert "_score" not in results[0]


def test_rerank_fetch_k_is_clamped_by_file_filtered_total_chunks():
    import rag.search as search_mod

    store = FakeStore(total_chunks=2)

    class FakeRerank:
        ready = True

        def rerank(self, query, items, top_k):
            return items[:top_k]

    search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="dense", top_k=5, rerank=True, fetch_k=20, file_ids=["file_a"]),
        rerank=FakeRerank(),
        store=store,
    ).execute()

    assert ("get_total_chunks", ("file_a",)) in store.calls
    assert ("search_dense", "query", 2, ("file-filter", ("file_a",))) in store.calls


def test_executor_invokes_runnable_with_file_id_langsmith_metadata(monkeypatch):
    import rag.search as search_mod

    captured = {}

    class FakeRunnable:
        def invoke(self, input_value, config=None):
            captured["input"] = input_value
            captured["config"] = config
            return []

    plan = search_mod.SearchPlan(
        "query",
        mode="hybrid",
        top_k=3,
        rerank=True,
        fetch_k=9,
        dense_weight=0.4,
        sparse_weight=0.6,
        rrf_k=30,
        file_ids=["file_a"],
    )
    executor = search_mod._SearchExecutor(plan, store=FakeStore())
    monkeypatch.setattr(executor, "_build_runnable", lambda: FakeRunnable())

    assert executor.execute() == []
    assert captured["input"] is None
    assert captured["config"]["run_name"] == "search"
    assert "rag-search" in captured["config"]["tags"]
    assert "mode:hybrid" in captured["config"]["tags"]
    assert captured["config"]["metadata"] == {
        "query": "query",
        "app_id": None,
        "mode": "hybrid",
        "top_k": 3,
        "rerank": True,
        "fetch_k": 9,
        "dense_weight": 0.4,
        "sparse_weight": 0.6,
        "rrf_k": 30,
        "file_ids": ["file_a"],
    }


def test_executor_logs_search_trace_with_file_ids_when_enabled(monkeypatch):
    import rag.search as search_mod
    from rag.logging_config import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    trace_logger = logging.getLogger("rag.trace")
    old_handlers = trace_logger.handlers
    old_propagate = trace_logger.propagate
    old_level = trace_logger.level
    trace_logger.handlers = [handler]
    trace_logger.propagate = False
    trace_logger.setLevel(logging.INFO)

    class FakeRunnable:
        def invoke(self, input_value, config=None):
            return [{"content": "answer", "metadata": {}}]

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", app_id="imsdom", mode="dense", top_k=1, file_ids=["file_a"]),
        store=FakeStore(),
        search_trace=True,
    )
    monkeypatch.setattr(executor, "_build_runnable", lambda: FakeRunnable())

    try:
        assert executor.execute() == [{"content": "answer", "metadata": {}}]
    finally:
        trace_logger.handlers = old_handlers
        trace_logger.propagate = old_propagate
        trace_logger.setLevel(old_level)

    row = json.loads(stream.getvalue())
    assert row["logger"] == "rag.trace"
    assert row["event"] == "search_trace"
    assert row["query"] == "query"
    assert row["app_id"] == "imsdom"
    assert row["mode"] == "dense"
    assert row["file_ids"] == ["file_a"]


def test_executor_search_trace_stages_include_backend_and_retriever_fields():
    import rag.search as search_mod

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="hybrid", top_k=2, dense_weight=0.5, sparse_weight=0.5),
        sparse=ReadySparse(),
        store=FakeStore(),
        store_backend="qdrant",
        search_trace=True,
    )

    assert [item["id"] for item in executor.execute()] == ["dense-1", "app-sparse-1"]

    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert stages["dense"]["backend"] == "qdrant"
    assert stages["dense"]["retriever"] == "dense"
    assert stages["dense"]["hit_count"] == 1
    assert stages["sparse"]["backend"] == "app"
    assert stages["sparse"]["retriever"] == "bm25"
    assert stages["sparse"]["hit_count"] == 1
    assert stages["fusion"]["backend"] == "app"
    assert stages["fusion"]["retriever"] == "fusion"
    assert stages["fusion"]["hit_count"] == 2


def test_dense_trace_splits_query_embedding_and_vector_query():
    import rag.search as search_mod

    store = FakeTracedVectorStore()
    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="dense", top_k=2),
        store=store,
        store_backend="qdrant",
        search_trace=True,
    )

    assert [item["id"] for item in executor.execute()] == ["dense-1"]

    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert stages["dense_encode"]["backend"] == "model"
    assert stages["dense_encode"]["retriever"] == "dense"
    assert stages["dense_query"]["backend"] == "qdrant"
    assert stages["dense_query"]["retriever"] == "dense"
    assert stages["dense_query"]["hit_count"] == 1
    assert store.calls == [
        ("build_file_filter", ()),
        ("encode_dense_query", "query"),
        ("query_dense_vector", [0.1, 0.2, 0.3], 2, ("file-filter", ())),
    ]


def test_hybrid_executor_uses_vector_sparse_backend():
    import rag.search as search_mod

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="hybrid", top_k=3, dense_weight=0.5, sparse_weight=0.5),
        sparse=ReadySparse(),
        store=FakeVectorSparseStore(),
        store_backend="qdrant",
        search_trace=True,
    )

    results = executor.execute()
    assert {item["id"] for item in results} == {"dense-1", "vector-sparse-1"}
    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert "bm25" not in stages
    assert stages["sparse"]["backend"] == "qdrant"
    assert stages["sparse"]["retriever"] == "sparse_vector"
    assert stages["sparse"]["hit_count"] == 1


def test_hybrid_executor_uses_indexed_sparse_backend():
    import rag.search as search_mod

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", app_id="imsdom", mode="hybrid", top_k=3, file_ids=["file_a"], dense_weight=0.5, sparse_weight=0.5),
        sparse=ReadyIndexedSparse(),
        store=FakeStore(),
        search_trace=True,
    )

    results = executor.execute()
    assert {item["id"] for item in results} == {"dense-1", "bm25-1"}
    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert stages["sparse"]["backend"] == "opensearch"
    assert stages["sparse"]["retriever"] == "bm25"
    assert stages["sparse"]["hit_count"] == 1
    assert results[1]["metadata"] == {"app_id": "imsdom", "file_ids": ["file_a"]}


def test_search_service_rejects_sparse_mode_when_sparse_is_disabled(monkeypatch):
    from fastapi import HTTPException

    from rag.api.runtime import runtime
    from rag.api.schemas import SearchRequest
    from rag.api.services import search as service
    from rag.auth import Principal

    monkeypatch.setattr(service, "require_ready", lambda: None)
    monkeypatch.setattr(runtime.application, "sparse", None)

    with pytest.raises(HTTPException) as exc:
        service.search(SearchRequest(query="query", app_id="imsdom", mode="sparse"), Principal(type="admin", app_id=""))

    assert exc.value.status_code == 400
    assert exc.value.detail == "sparse is not enabled"


def test_search_service_falls_back_hybrid_to_dense_when_sparse_is_disabled(monkeypatch):
    from rag.api.runtime import runtime
    from rag.api.schemas import SearchRequest
    from rag.api.services import search as service
    from rag.auth import Principal

    store = FakeStore()
    monkeypatch.setattr(service, "require_ready", lambda: None)
    monkeypatch.setattr(runtime.application, "sparse", None)
    monkeypatch.setattr(runtime.application, "rerank", None)
    monkeypatch.setattr(runtime.application, "store", store)

    body = service.search(SearchRequest(query="query", app_id="imsdom", mode="hybrid"), Principal(type="admin", app_id=""))

    assert body["mode"] == "dense"
    assert [item["id"] for item in body["results"]] == ["dense-1"]
    assert ("search_dense", "query", 5, ("file-filter", ())) in store.calls


def test_executor_does_not_log_search_trace_when_disabled(monkeypatch):
    import rag.search as search_mod
    from rag.logging_config import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    trace_logger = logging.getLogger("rag.trace")
    old_handlers = trace_logger.handlers
    old_propagate = trace_logger.propagate
    old_level = trace_logger.level
    trace_logger.handlers = [handler]
    trace_logger.propagate = False
    trace_logger.setLevel(logging.INFO)

    class FakeRunnable:
        def invoke(self, input_value, config=None):
            return []

    executor = search_mod._SearchExecutor(search_mod.SearchPlan("query", mode="dense", top_k=1), store=FakeStore(), search_trace=False)
    monkeypatch.setattr(executor, "_build_runnable", lambda: FakeRunnable())

    try:
        assert executor.execute() == []
    finally:
        trace_logger.handlers = old_handlers
        trace_logger.propagate = old_propagate
        trace_logger.setLevel(old_level)

    assert stream.getvalue() == ""
