import json
import logging
import time
from dataclasses import replace
from contextlib import nullcontext
from io import StringIO

import pytest


pytestmark = pytest.mark.unit


def test_dense_search_uses_top_k_without_rerank_fetch_limit():
    from services.rag.core.search import SearchPlan, _SearchExecutor
    from services.rag.core.api.schemas import SearchRequest

    request = SearchRequest(query="query", top_k=50, rerank=False, rerank_fetch_k=20)
    plan = SearchPlan(request.query, top_k=request.top_k, rerank=False, rerank_fetch_k=request.rerank_fetch_k)
    vector = FakeVector()

    results = _SearchExecutor(plan, vector=vector).execute()

    assert results
    assert ("search_dense", "query", 50, ("file-filter", ())) in vector.calls


class FakeVector:
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

    def app_scope(self, app_id):
        self.calls.append(("app_scope", app_id))
        return nullcontext()

    def search_dense(self, query, limit, metadata_filter):
        self.calls.append(("search_dense", query, limit, metadata_filter))
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "_score": 0.8}]


class FakeTracedVector(FakeVector):
    def encode_dense_query(self, query):
        self.calls.append(("encode_dense_query", query))
        return [0.1, 0.2, 0.3]

    def query_dense_vector(self, query_vector, limit, metadata_filter):
        self.calls.append(("query_dense_vector", query_vector, limit, metadata_filter))
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "_score": 0.8}]


class FakeSparseVector(FakeTracedVector):
    def encode_sparse_query(self, query):
        self.calls.append(("encode_sparse_query", query))
        return {1: 0.5}

    def query_sparse_vector(self, query_vector, limit, metadata_filter):
        self.calls.append(("query_sparse_vector", query_vector, limit, metadata_filter))
        return [{"id": "sparse-1", "content": "sparse", "metadata": {}, "_score": 0.7}]


class FakeRerank:
    def __init__(self):
        self.calls = []

    def rerank(self, query, items, top_k):
        self.calls.append((query, [item["id"] for item in items], top_k))
        ranked = list(reversed(items))
        for index, item in enumerate(ranked):
            item["_score"] = 1.0 - index * 0.1
        return ranked[:top_k]


def _state(*, config, vector, inference=None, vector_backend="qdrant"):
    return type(
        "State",
        (),
        {
            "ready": True,
            "config": config,
            "inference_client": inference or type("Inference", (), {"rerank": None})(),
            "vector_client": vector,
            "vector_backend": vector_backend,
        },
    )()


def _config():
    from shared.config import parse_app_config

    return parse_app_config({
        "auth": {"admin": {"username": "admin", "password": "admin123"}},
        "database": {"provider": "postgres", "url": "postgresql://rag:rag@postgres:5432/rag"},
        "services": {
            "parser": {"base_url": "http://parser:7000"},
            "inference": {"base_url": "http://inference:7001"},
            "vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"},
        },
    })


def test_search_plan_uses_file_ids():
    import services.rag.core.search as search_mod

    plan = search_mod.SearchPlan("query", file_ids=["file_a", "file_b"])

    assert plan.file_ids == ["file_a", "file_b"]


def test_search_plan_rejects_empty_file_ids():
    import services.rag.core.search as search_mod

    with pytest.raises(ValueError, match="file_ids cannot be empty"):
        search_mod.SearchPlan("query", file_ids=[])


def test_vector_backend_uses_vector_backend_name_when_config_is_absent():
    from services.rag.core.search.pipeline import _vector_backend

    class CustomVector:
        backend_name = "custom-vector"

    assert _vector_backend(CustomVector()) == "custom-vector"


def test_search_plan_limits_file_ids_to_1000():
    import services.rag.core.search as search_mod

    with pytest.raises(ValueError, match="file_ids exceeds max limit: 1000"):
        search_mod.SearchPlan("query", file_ids=[f"f{i}" for i in range(1001)])


def test_executor_searches_single_chunks_collection_with_file_filter():
    import services.rag.core.search as search_mod

    vector = FakeVector()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=5, file_ids=["file_a"]),
        vector=vector,
    ).execute()

    assert [item["id"] for item in results] == ["dense-1"]
    assert ("build_file_filter", ("file_a",)) in vector.calls
    assert ("search_dense", "query", 5, ("file-filter", ("file_a",))) in vector.calls


def test_executor_exposes_retrieval_score():
    import services.rag.core.search as search_mod

    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=1),
        vector=FakeVector(),
    ).execute()

    assert results[0]["score"] == 0.8
    assert "_score" not in results[0]


def test_executor_invokes_runnable_with_file_id_langsmith_metadata(monkeypatch):
    import services.rag.core.search as search_mod

    captured = {}

    class FakeRunnable:
        def invoke(self, input_value, config=None):
            captured["input"] = input_value
            captured["config"] = config
            return []

    plan = search_mod.SearchPlan(
        "query",
        top_k=3,
        file_ids=["file_a"],
    )
    executor = search_mod._SearchExecutor(plan, vector=FakeVector())
    monkeypatch.setattr(executor, "_build_runnable", lambda: FakeRunnable())

    assert executor.execute() == []
    assert captured["input"] is None
    assert captured["config"]["run_name"] == "search"
    assert "rag-search" in captured["config"]["tags"]
    assert "mode:dense" in captured["config"]["tags"]
    assert captured["config"]["metadata"] == {
        "query": "query",
        "app_id": None,
        "mode": "dense",
            "top_k": 3,
            "rerank_fetch_k": None,
            "rerank": False,
            "rrf_k": 60,
            "file_ids": ["file_a"],
        }


def test_executor_logs_search_trace_with_file_ids_when_enabled(monkeypatch):
    import services.rag.core.search as search_mod
    from shared.logging_config import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    trace_logger = logging.getLogger("services.rag.trace")
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
        search_mod.SearchPlan("query", app_id="imsdom", top_k=1, file_ids=["file_a"]),
        vector=FakeVector(),
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
    assert row["logger"] == "services.rag.trace"
    assert row["event"] == "search_trace"
    assert row["query"] == "query"
    assert row["app_id"] == "imsdom"
    assert row["mode"] == "dense"
    assert row["file_ids"] == ["file_a"]


def test_executor_search_trace_stages_include_backend_and_retriever_fields():
    import services.rag.core.search as search_mod

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2),
        vector=FakeVector(),
        vector_backend="qdrant",
        search_trace=True,
    )

    assert [item["id"] for item in executor.execute()] == ["dense-1"]

    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert stages["dense"]["backend"] == "qdrant"
    assert stages["dense"]["retriever"] == "dense"
    assert stages["dense"]["hit_count"] == 1


def test_dense_trace_splits_query_embedding_and_vector_query():
    import services.rag.core.search as search_mod

    vector = FakeTracedVector()
    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2),
        vector=vector,
        vector_backend="qdrant",
        search_trace=True,
    )

    assert [item["id"] for item in executor.execute()] == ["dense-1"]

    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert stages["dense_encode"]["backend"] == "model"
    assert stages["dense_encode"]["retriever"] == "dense"
    assert stages["dense_query"]["backend"] == "qdrant"
    assert stages["dense_query"]["retriever"] == "dense"
    assert stages["dense_query"]["hit_count"] == 1
    assert vector.calls == [
        ("build_file_filter", ()),
        ("encode_dense_query", "query"),
        ("query_dense_vector", [0.1, 0.2, 0.3], 2, ("file-filter", ())),
    ]


def test_executor_uses_sparse_search_mode():
    import services.rag.core.search as search_mod

    vector = FakeSparseVector()
    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="sparse"),
        vector=vector,
        vector_backend="qdrant",
        search_trace=True,
    )

    assert [item["id"] for item in executor.execute()] == ["sparse-1"]
    assert ("query_sparse_vector", {1: 0.5}, 2, ("file-filter", ())) in vector.calls


def test_executor_hybrid_merges_dense_and_sparse_results():
    import services.rag.core.search as search_mod

    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            self.calls.append(("query_dense_vector", query_vector, limit, metadata_filter))
            return [{"id": "shared", "content": "dense", "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            self.calls.append(("query_sparse_vector", query_vector, limit, metadata_filter))
            return [
                {"id": "shared", "content": "dense", "metadata": {}, "_score": 0.4},
                {"id": "sparse-only", "content": "sparse", "metadata": {}, "_score": 0.9},
            ]

    vector = Vector()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="hybrid", rrf_k=60),
        vector=vector,
    ).execute()

    assert [item["id"] for item in results] == ["shared", "sparse-only"]
    assert results[0]["score"] == pytest.approx(2 / 61)


def test_executor_hybrid_runs_dense_and_sparse_in_parallel():
    import services.rag.core.search as search_mod

    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            time.sleep(0.15)
            return [{"id": "dense", "content": "dense", "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            time.sleep(0.15)
            return [{"id": "sparse", "content": "sparse", "metadata": {}, "_score": 0.7}]

    started = time.perf_counter()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="hybrid"),
        vector=Vector(),
    ).execute()

    assert {item["id"] for item in results} == {"dense", "sparse"}
    assert time.perf_counter() - started < 0.25


def test_executor_hybrid_preserves_app_collection_scope_in_parallel_threads():
    import services.rag.core.search as search_mod
    from services.rag.core.scope import app_collection, current_collection

    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            return [{"id": "dense", "content": current_collection(), "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            return [{"id": "sparse", "content": current_collection(), "metadata": {}, "_score": 0.7}]

    with app_collection("imsdom"):
        results = search_mod._SearchExecutor(
            search_mod.SearchPlan("query", top_k=2, mode="hybrid"),
            vector=Vector(),
        ).execute()

    assert {item["content"] for item in results} == {"imsdom_chunks"}


def test_search_sparse_uses_app_collection_scope():
    from services.rag.core.api.services import search as search_service
    from services.rag.core.auth import Principal
    from services.rag.core.scope import app_collection, current_collection

    class Vector(FakeSparseVector):
        def supports_sparse_vector(self):
            return True

        def app_scope(self, app_id):
            return app_collection(app_id)

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            self.calls.append(("query_sparse_vector", current_collection()))
            return [{"id": "sparse", "content": current_collection(), "metadata": {}, "_score": 0.7}]

    config = _config()
    req = type("Req", (), {"query": "query", "app_id": "imsdom", "mode": "sparse", "top_k": 1, "rerank": False, "rerank_fetch_k": None, "rrf_k": None, "file_ids": None})()
    state = _state(config=config, vector=Vector(), vector_backend="milvus")

    response = search_service.search(state, req, Principal(type="admin", app_id=""))

    assert response["results"][0]["content"] == "imsdom_chunks"


def test_executor_hybrid_falls_back_to_dense_when_sparse_upstream_fails():
    import services.rag.core.search as search_mod
    from shared.upstream import UpstreamServiceError

    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            return [{"id": "dense", "content": "dense", "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            raise UpstreamServiceError(
                service="inference",
                error="inference returned HTTP 404",
                retryable=False,
                status_code=502,
            )

    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="hybrid"),
        vector=Vector(),
    ).execute()

    assert [item["id"] for item in results] == ["dense"]


def test_executor_reranks_dense_candidates_when_rerank_client_is_configured():
    import services.rag.core.search as search_mod

    class Vector(FakeVector):
        def search_dense(self, query, limit, metadata_filter):
            self.calls.append(("search_dense", query, limit, metadata_filter))
            return [
                {"id": "a", "content": "a", "metadata": {}, "_score": 0.1},
                {"id": "b", "content": "b", "metadata": {}, "_score": 0.2},
                {"id": "c", "content": "c", "metadata": {}, "_score": 0.3},
            ][:limit]

    vector = Vector()
    rerank = FakeRerank()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, rerank_fetch_k=3, rerank=True),
        vector=vector,
        rerank=rerank,
    ).execute()

    assert [item["id"] for item in results] == ["c", "b"]
    assert ("search_dense", "query", 3, ("file-filter", ())) in vector.calls
    assert rerank.calls == [("query", ["a", "b", "c"], 2)]


def test_executor_returns_retrieved_items_when_rerank_fails(caplog):
    import services.rag.core.search as search_mod
    from shared.upstream import UpstreamServiceError

    class Vector(FakeVector):
        def search_dense(self, query, limit, metadata_filter):
            return [
                {"id": "a", "content": "a", "metadata": {}, "_score": 0.1},
                {"id": "b", "content": "b", "metadata": {}, "_score": 0.2},
                {"id": "c", "content": "c", "metadata": {}, "_score": 0.3},
            ][:limit]

    class FailingRerank:
        def rerank(self, query, items, top_k):
            raise UpstreamServiceError(
                service="inference",
                error="inference returned HTTP 503",
                retryable=True,
                status_code=503,
            )

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, rerank_fetch_k=3, rerank=True),
        vector=Vector(),
        rerank=FailingRerank(),
        search_trace=True,
    )

    with caplog.at_level(logging.WARNING):
        results = executor.execute()

    assert [item["id"] for item in results] == ["c", "b"]
    stages = {stage["name"]: stage for stage in executor.trace.result["stages"]}
    assert stages["rerank"]["error"] == "inference returned HTTP 503"
    assert any(record.message == "rerank failed, return retrieved items" for record in caplog.records)


def test_search_service_uses_dense_search(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    vector = FakeVector()
    config = _config()
    state = _state(config=replace(config, search=replace(config.search, rerank=False)), vector=vector)

    body = service.search(state, SearchRequest(query="query", app_id="imsdom"), Principal(type="admin", app_id=""))

    assert body["mode"] == "dense"
    assert [item["id"] for item in body["results"]] == ["dense-1"]
    assert ("search_dense", "query", 5, ("file-filter", ())) in vector.calls


def test_search_service_rejects_sparse_mode_when_vector_has_no_sparse():
    from fastapi import HTTPException
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    config = _config()
    state = _state(config=replace(config, search=replace(config.search, mode="dense")), vector=FakeVector())

    with pytest.raises(HTTPException) as exc:
        service.search(state, SearchRequest(query="query", app_id="imsdom", mode="sparse"), Principal(type="admin", app_id=""))

    assert exc.value.status_code == 400
    assert exc.value.detail == "sparse search is not configured"


def test_search_service_falls_back_to_dense_when_hybrid_has_no_sparse():
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    vector = FakeVector()
    config = _config()
    state = _state(config=replace(config, search=replace(config.search, mode="hybrid", rerank=False)), vector=vector)

    body = service.search(state, SearchRequest(query="query", app_id="imsdom"), Principal(type="admin", app_id=""))

    assert body["mode"] == "dense"
    assert [item["id"] for item in body["results"]] == ["dense-1"]
    assert ("search_dense", "query", 5, ("file-filter", ())) in vector.calls


def test_search_service_preserves_upstream_error(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal
    from shared.upstream import UpstreamServiceError

    class FailingExecutor:
        def __init__(self, *args, **kwargs):
            self.trace = type("Trace", (), {"result": {}})()

        def execute(self):
            raise UpstreamServiceError(
                service="inference",
                error="inference request timed out",
                retryable=True,
                status_code=504,
            )

    monkeypatch.setattr(service, "_SearchExecutor", FailingExecutor)
    config = _config()
    state = _state(config=replace(config, search=replace(config.search, rerank=False)), vector=FakeVector())

    with pytest.raises(UpstreamServiceError) as exc:
        service.search(state, SearchRequest(query="query", app_id="imsdom"), Principal(type="admin", app_id=""))

    assert exc.value.status_code == 504
    assert exc.value.retryable is True
    assert exc.value.error == "inference request timed out"


@pytest.mark.parametrize("entrypoint", ["search", "client_search"])
def test_search_returns_sdk_error_details(monkeypatch, entrypoint, caplog):
    import asyncio
    import json
    from shared.api_errors import upstream_exception_handler
    from shared.upstream import UpstreamServiceError
    from pymilvus.exceptions import MilvusException
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    error = MilvusException(code=1100, message="fieldName(sparse_vector) not found")

    class FailingExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self):
            raise error

    monkeypatch.setattr(service, "_SearchExecutor", FailingExecutor)
    config = _config()
    state = _state(config=replace(config, search=replace(config.search, rerank=False)), vector=FakeVector())
    with pytest.raises(UpstreamServiceError) as raised:
        getattr(service, entrypoint)(state, SearchRequest(query="query", app_id="imsdom"), Principal(type="admin", app_id=""))
    response = asyncio.run(upstream_exception_handler(None, raised.value))
    assert response.status_code == 500
    body = json.loads(response.body)
    assert body == {"error": str(error), "service": "rag", "retryable": False, "traceId": raised.value.trace_id}
    assert body["traceId"]
    assert any(record.exc_info and record.exc_info[1] is error for record in caplog.records)


def test_search_service_passes_configured_rerank_to_executor(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    captured = {}

    class FailingExecutor:
        def __init__(self, plan, vector, rerank=None, **kwargs):
            captured["plan"] = plan
            captured["rerank"] = rerank
            self.trace = type("Trace", (), {"result": {"elapsed_ms": 1.0}})()

        def execute(self):
            return []

    rerank = FakeRerank()
    inference = type("Inference", (), {"rerank": rerank})()
    monkeypatch.setattr(service, "_SearchExecutor", FailingExecutor)
    config = _config()
    state = _state(
        config=replace(config, search=replace(config.search, top_k=5, rerank_fetch_k=20, rerank=True)),
        vector=FakeVector(),
        inference=inference,
    )

    body = service.search(state, SearchRequest(query="query", app_id="imsdom", top_k=3), Principal(type="admin", app_id=""))

    assert captured["plan"].top_k == 3
    assert captured["plan"].rerank_fetch_k == 20
    assert captured["plan"].rerank is True
    assert captured["rerank"] is rerank
    assert body["rerank"] is True
    assert body["rerank_fetch_k"] == 20


def test_search_service_request_can_disable_configured_rerank(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    captured = {}

    class FailingExecutor:
        def __init__(self, plan, vector, rerank=None, **kwargs):
            captured["plan"] = plan
            captured["rerank"] = rerank
            self.trace = type("Trace", (), {"result": {"elapsed_ms": 1.0}})()

        def execute(self):
            return []

    rerank = FakeRerank()
    inference = type("Inference", (), {"rerank": rerank})()
    monkeypatch.setattr(service, "_SearchExecutor", FailingExecutor)
    config = _config()
    state = _state(
        config=replace(config, search=replace(config.search, top_k=5, rerank_fetch_k=20, rerank=True)),
        vector=FakeVector(),
        inference=inference,
    )

    body = service.search(state, SearchRequest(query="query", app_id="imsdom", rerank=False), Principal(type="admin", app_id=""))

    assert captured["plan"].rerank is False
    assert captured["plan"].rerank_fetch_k == 20
    assert captured["rerank"] is rerank
    assert body["rerank"] is False
    assert body["rerank_fetch_k"] is None


def test_search_service_request_can_enable_unchecked_rerank(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    captured = {}

    class FailingExecutor:
        def __init__(self, plan, vector, rerank=None, **kwargs):
            captured["plan"] = plan
            captured["rerank"] = rerank
            self.trace = type("Trace", (), {"result": {"elapsed_ms": 1.0}})()

        def execute(self):
            return []

    rerank = FakeRerank()
    inference = type("Inference", (), {"rerank": rerank})()
    monkeypatch.setattr(service, "_SearchExecutor", FailingExecutor)
    config = _config()
    state = _state(
        config=replace(config, search=replace(config.search, top_k=5, rerank_fetch_k=20, rerank=False)),
        vector=FakeVector(),
        inference=inference,
    )

    body = service.search(state, SearchRequest(query="query", app_id="imsdom", rerank=True), Principal(type="admin", app_id=""))

    assert captured["plan"].rerank is True
    assert captured["rerank"] is rerank
    assert body["rerank"] is True
    assert body["rerank_fetch_k"] == 20


def test_search_service_falls_back_when_rerank_client_is_unavailable(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    captured = {}

    class Executor:
        def __init__(self, plan, vector, rerank=None, **kwargs):
            captured["plan"] = plan
            captured["rerank"] = rerank
            self.trace = type("Trace", (), {"result": {"elapsed_ms": 1.0}})()

        def execute(self):
            return []

    monkeypatch.setattr(service, "_SearchExecutor", Executor)
    config = _config()
    state = _state(config=replace(config, search=replace(config.search, rerank=False)), vector=FakeVector())

    body = service.search(state, SearchRequest(query="query", app_id="imsdom", rerank=True), Principal(type="admin", app_id=""))

    assert captured["plan"].rerank is False
    assert captured["rerank"] is None
    assert body["rerank"] is False
    assert body["rerank_fetch_k"] is None


def test_search_service_request_can_override_rerank_fetch_k(monkeypatch):
    from services.rag.core.api.schemas import SearchRequest
    from services.rag.core.api.services import search as service
    from services.rag.core.auth import Principal

    captured = {}

    class FailingExecutor:
        def __init__(self, plan, vector, rerank=None, **kwargs):
            captured["plan"] = plan
            self.trace = type("Trace", (), {"result": {"elapsed_ms": 1.0}})()

        def execute(self):
            return []

    monkeypatch.setattr(service, "_SearchExecutor", FailingExecutor)
    config = _config()
    state = _state(
        config=replace(config, search=replace(config.search, top_k=5, rerank_fetch_k=20, rerank=True)),
        vector=FakeVector(),
        inference=type("Inference", (), {"rerank": FakeRerank()})(),
    )

    body = service.search(state, SearchRequest(query="query", app_id="imsdom", top_k=3, rerank=True, rerank_fetch_k=8), Principal(type="admin", app_id=""))

    assert captured["plan"].top_k == 3
    assert captured["plan"].rerank is True
    assert captured["plan"].rerank_fetch_k == 8
    assert body["rerank_fetch_k"] == 8


def test_executor_does_not_log_search_trace_when_disabled(monkeypatch):
    import services.rag.core.search as search_mod
    from shared.logging_config import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    trace_logger = logging.getLogger("services.rag.trace")
    old_handlers = trace_logger.handlers
    old_propagate = trace_logger.propagate
    old_level = trace_logger.level
    trace_logger.handlers = [handler]
    trace_logger.propagate = False
    trace_logger.setLevel(logging.INFO)

    class FakeRunnable:
        def invoke(self, input_value, config=None):
            return []

    executor = search_mod._SearchExecutor(search_mod.SearchPlan("query", top_k=1), vector=FakeVector(), search_trace=False)
    monkeypatch.setattr(executor, "_build_runnable", lambda: FakeRunnable())

    try:
        assert executor.execute() == []
    finally:
        trace_logger.handlers = old_handlers
        trace_logger.propagate = old_propagate
        trace_logger.setLevel(old_level)

    assert stream.getvalue() == ""
