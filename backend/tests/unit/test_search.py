import pytest
import json
import logging
from io import StringIO


pytestmark = pytest.mark.unit


class TestSearchPlan:
    def test_construction_does_not_touch_store(self):
        """SearchPlan 只描述查询计划,构造时不读取全集或访问检索器。"""
        import search as search_mod

        plan = search_mod.SearchPlan("query", mode="hybrid", top_k=20, rerank=True, fetch_k=100)

        assert plan.query == "query"
        assert plan.mode == "hybrid"
        assert plan.top_k == 20
        assert plan.rerank is True
        assert plan.fetch_k == 100

    def test_no_rerank_keeps_top_k_and_default_fetch_k(self):
        """无重排计划保留 top_k,fetch_k 只是默认值,执行期不会使用。"""
        import search as search_mod

        plan = search_mod.SearchPlan("query", mode="dense", top_k=7)

        assert plan.top_k == 7
        assert plan.fetch_k == 100
        assert plan.rerank is False

    def test_rerank_keeps_top_k_and_fetch_k(self):
        """重排计划同时描述最终返回条数 top_k 和候选池 fetch_k。"""
        import search as search_mod

        plan = search_mod.SearchPlan("query", mode="dense", top_k=3, rerank=True, fetch_k=30)

        assert plan.top_k == 3
        assert plan.fetch_k == 30
        assert plan.rerank is True


def test_executor_builds_runnable_pipeline_with_parallel_retrieval():
    import search as search_mod
    from langchain_core.runnables import RunnableParallel, RunnableSequence

    class FakeStore:
        def get_total_chunks(self, namespace="default", scope_ids=None):
            return 10

        def build_common_filter(self, namespace):
            return ("common", namespace)

        def build_scoped_filter(self, namespace, scope_ids):
            return ("scoped", namespace, tuple(scope_ids))

        def sparse_uses_store(self, sparse=None):
            return False

    class ReadySparse:
        ready = True

        def search(self, query, documents, limit):
            return []

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="hybrid", top_k=5, scope_ids=["scope_001"]),
        sparse=ReadySparse(),
        store=FakeStore(),
    )

    runnable = executor._build_runnable()

    assert isinstance(runnable, RunnableSequence)
    retrieve_parallel = next(step for step in runnable.steps if isinstance(step, RunnableParallel))
    assert set(retrieve_parallel.steps__) == {"common", "scoped"}

    common_branch = retrieve_parallel.steps__["common"]
    assert isinstance(common_branch, RunnableSequence)
    assert any(
        isinstance(step, RunnableParallel) and set(step.steps__) == {"dense", "sparse"}
        for step in common_branch.steps
    )


def test_dense_and_sparse_retrieval_nodes_are_langchain_retrievers():
    import search as search_mod
    from langchain_core.retrievers import BaseRetriever
    from langchain_core.runnables import RunnableParallel

    class FakeStore:
        def get_total_chunks(self, namespace="default", scope_ids=None):
            return 10

        def build_common_filter(self, namespace):
            return ("common", namespace)

        def build_scoped_filter(self, namespace, scope_ids):
            return ("scoped", namespace, tuple(scope_ids))

        def sparse_uses_store(self, sparse=None):
            return False

    class ReadySparse:
        ready = True

        def search(self, query, documents, limit):
            return []

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", mode="hybrid", top_k=5),
        sparse=ReadySparse(),
        store=FakeStore(),
    )

    common_branch = next(
        step for step in executor._build_runnable().steps
        if isinstance(step, RunnableParallel)
    ).steps__["common"]
    retrieve_parallel = next(
        step for step in common_branch.steps
        if isinstance(step, RunnableParallel)
    )

    assert isinstance(retrieve_parallel.steps__["dense"], BaseRetriever)
    assert isinstance(retrieve_parallel.steps__["sparse"], BaseRetriever)


def test_executor_invokes_runnable_with_langsmith_metadata(monkeypatch):
    import search as search_mod

    captured = {}

    class FakeRunnable:
        def invoke(self, input_value, config=None):
            captured["input"] = input_value
            captured["config"] = config
            return []

    class FakeStore:
        def get_total_chunks(self, namespace="default", scope_ids=None):
            return 10

    plan = search_mod.SearchPlan(
        "query",
        mode="hybrid",
        top_k=3,
        rerank=True,
        fetch_k=9,
        namespace="tenant_a",
        scope_ids=["scope_001"],
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
        "mode": "hybrid",
        "top_k": 3,
        "rerank": True,
        "fetch_k": 9,
        "namespace": "tenant_a",
        "scope_ids": ["scope_001"],
    }


def test_executor_logs_search_trace_when_enabled(monkeypatch):
    import search as search_mod
    from logging_config import JsonFormatter

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

    class FakeStore:
        def get_total_chunks(self, namespace="default", scope_ids=None):
            return 10

    executor = search_mod._SearchExecutor(search_mod.SearchPlan("query", mode="dense", top_k=1), store=FakeStore(), search_trace=True)
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
    assert row["mode"] == "dense"
    assert row["top_k"] == 1
    assert row["status"] == "ok"
    assert row["result_count"] == 1
    assert isinstance(row["elapsed_ms"], float)
    assert isinstance(row["stages"], list)


def test_executor_does_not_log_search_trace_when_disabled(monkeypatch):
    import search as search_mod
    from logging_config import JsonFormatter

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

    class FakeStore:
        def get_total_chunks(self, namespace="default", scope_ids=None):
            return 10

    executor = search_mod._SearchExecutor(search_mod.SearchPlan("query", mode="dense", top_k=1), store=FakeStore(), search_trace=False)
    monkeypatch.setattr(executor, "_build_runnable", lambda: FakeRunnable())

    try:
        assert executor.execute() == []
    finally:
        trace_logger.handlers = old_handlers
        trace_logger.propagate = old_propagate
        trace_logger.setLevel(old_level)

    assert stream.getvalue() == ""
