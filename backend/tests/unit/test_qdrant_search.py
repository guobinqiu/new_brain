import pytest
import threading
import time
from langchain_core.documents import Document
from langchain_qdrant.sparse_embeddings import SparseEmbeddings, SparseVector


pytestmark = pytest.mark.unit


class ReadyMemorySparse:
    ready = True

    def search(self, query, documents, limit):
        items = []
        for document in documents:
            item = dict(document)
            item["_score"] = 1.0
            items.append(item)
        return items[:limit]


class FakeBackendStore:
    def __init__(self, store_factory=None, documents_factory=None, store_sparse=False, total_chunks=100):
        self.store_factory = store_factory or (lambda collection_type, mode: None)
        self.documents_factory = documents_factory or (lambda collection_type, metadata_filter: [])
        self.store_sparse = store_sparse
        self.total_chunks = total_chunks

    def search_dense(self, collection_type, query, limit, metadata_filter):
        return self._search_with_store(collection_type, "dense", query, limit, metadata_filter)

    def search_sparse(self, collection_type, query, limit, metadata_filter):
        return self._search_with_store(collection_type, "sparse", query, limit, metadata_filter)

    def search_hybrid(self, collection_type, query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k):
        return self._search_with_store(collection_type, "hybrid", query, limit, metadata_filter)

    def _search_with_store(self, collection_type, mode, query, limit, metadata_filter):
        vector_store = self.store_factory(collection_type, mode)
        docs = vector_store.similarity_search_with_score(query, k=limit, filter=metadata_filter)
        items = []
        for doc, score in docs:
            metadata = dict(doc.metadata or {})
            items.append({
                "id": doc.id or metadata.get("source_id") or metadata.get("id", ""),
                "content": doc.page_content,
                "metadata": metadata,
                "collection_type": collection_type,
                "_score": float(score),
            })
        return items

    def build_common_filter(self, namespace):
        return ("common-filter", namespace)

    def build_scoped_filter(self, namespace, scope_ids):
        return ("scoped-filter", namespace, tuple(scope_ids))

    def get_search_documents(self, collection_type, metadata_filter):
        return self.documents_factory(collection_type, metadata_filter)

    def get_total_chunks(self, namespace="default", scope_ids=None):
        return self.total_chunks

    def sparse_uses_store(self, sparse=None):
        return self.store_sparse or isinstance(sparse, SparseEmbeddings)


def test_init_search_initializes_jieba(monkeypatch):
    import search
    from tokenizer.jieba_tokenizer import JiebaTokenizer

    calls = []
    monkeypatch.setattr(JiebaTokenizer, "start", lambda self: calls.append("jieba"))

    search.init_search()

    assert calls == ["jieba"]


def test_search_queries_common_and_scoped_then_prefers_scoped(monkeypatch):
    import search

    calls = []

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            calls.append((self.collection_type, query, k, filter))
            if self.collection_type == "common":
                return [
                    (Document(page_content="通用结果", metadata={"filename": "common.txt"}, id="common-1"), 0.7),
                ]
            return [
                (Document(page_content="专属结果", metadata={"filename": "scoped.txt", "scope_id": "scope_001"}, id="scoped-1"), 0.8),
            ]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type))
    plan = search.SearchPlan(
        "query",
        mode="hybrid",
        top_k=2,
        namespace="tenant_a",
        scope_ids=["scope_001"],
    )

    results = search._SearchExecutor(plan, sparse=ReadyMemorySparse(), store=backend_store).execute()

    assert [item["collection_type"] for item in results] == ["scoped", "common"]
    assert [item["content"] for item in results] == ["专属结果", "通用结果"]
    assert ("common", "query", 2, ("common-filter", "tenant_a")) in calls
    assert ("scoped", "query", 2, ("scoped-filter", "tenant_a", ("scope_001",))) in calls


def test_search_with_scope_ids_always_queries_common_and_scoped(monkeypatch):
    import search

    calls = []

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            calls.append((self.collection_type, query, k, filter))
            return [(Document(page_content=f"{self.collection_type}结果", metadata={}, id=f"{self.collection_type}-1"), 0.8)]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type))

    plan = search.SearchPlan(
        "query",
        mode="dense",
        top_k=5,
        namespace="tenant_a",
        scope_ids=["scope_001", "scope_002"],
    )

    results = search._SearchExecutor(plan, store=backend_store).execute()

    assert [result["collection_type"] for result in results] == ["scoped", "common"]
    assert ("common", "query", 5, ("common-filter", "tenant_a")) in calls
    assert ("scoped", "query", 5, ("scoped-filter", "tenant_a", ("scope_001", "scope_002"))) in calls


def test_search_without_scope_ids_only_queries_common_collection(monkeypatch):
    import search

    calls = []

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            calls.append((self.collection_type, query, k, filter))
            if self.collection_type == "common":
                return [(Document(page_content="通用内容", metadata={}, id="common-1"), 0.8)]
            return [(Document(page_content="设备年检 scope_alpha 专属内容", metadata={"scope_id": "scope_alpha"}, id="scoped-alpha-1"), 0.8)]

    def fail_scoped_filter(namespace, scope_ids):
        raise AssertionError("scope_ids 为空时不应该查询 scoped collection")

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type))
    backend_store.build_scoped_filter = fail_scoped_filter

    results = search._SearchExecutor(
        search.SearchPlan(
            "年检",
            mode="hybrid",
            top_k=5,
            namespace="default",
            scope_ids=[],
        ),
        sparse=ReadyMemorySparse(),
        store=backend_store,
    ).execute()

    assert [result["collection_type"] for result in results] == ["common"]
    assert results[0]["content"] == "通用内容"
    assert calls == [("common", "年检", 5, ("common-filter", "default"))]


def test_search_with_scope_alpha_queries_scoped_and_common(monkeypatch):
    import search

    calls = []

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            calls.append((self.collection_type, query, k, filter))
            if self.collection_type == "common":
                return [(Document(page_content="通用内容", metadata={}, id="common-1"), 0.34)]
            return [(Document(page_content="设备年检 scope_alpha 专属内容", metadata={"scope_id": "scope_alpha"}, id="scoped-alpha-1"), 0.62)]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type))

    results = search._SearchExecutor(
        search.SearchPlan(
            "年检",
            mode="hybrid",
            top_k=5,
            namespace="default",
            scope_ids=["scope_alpha"],
        ),
        sparse=ReadyMemorySparse(),
        store=backend_store,
    ).execute()

    assert [result["collection_type"] for result in results] == ["scoped", "common"]
    assert results[0]["content"] == "设备年检 scope_alpha 专属内容"
    assert ("scoped", "年检", 5, ("scoped-filter", "default", ("scope_alpha",))) in calls


def test_dense_keeps_low_score_results_and_sorts_by_score(monkeypatch):
    import search

    class FakeStore:
        def similarity_search_with_score(self, query, k, filter):
            return [
                (Document(page_content="相关结果", metadata={}, id="high"), 0.62),
                (Document(page_content="低分结果", metadata={}, id="low"), 0.34),
            ]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore())

    results = search._SearchExecutor(
        search.SearchPlan("年检", mode="dense", top_k=5, namespace="default"),
        store=backend_store,
    ).execute()

    assert [item["id"] for item in results] == ["high", "low"]


def test_search_pipeline_uses_store_search_methods_not_vector_store_wrapper(monkeypatch):
    import search

    class DirectSearchStore(FakeBackendStore):
        def search_dense(self, collection_type, query, limit, metadata_filter):
            return [{
                "id": "dense-direct",
                "content": "direct dense result",
                "metadata": {},
                "collection_type": collection_type,
                "_score": 0.8,
            }]

    results = search._SearchExecutor(
        search.SearchPlan("query", mode="dense", top_k=5, namespace="default"),
        store=DirectSearchStore(),
    ).execute()

    assert [item["id"] for item in results] == ["dense-direct"]
    assert not hasattr(search.Store, "get_store")


def test_non_rerank_results_are_globally_sorted_by_score(monkeypatch):
    import search

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            if self.collection_type == "common":
                return [(Document(page_content="高分通用", metadata={}, id="common-high"), 0.9)]
            return [(Document(page_content="低分专属", metadata={}, id="scoped-low"), 0.5)]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type))

    results = search._SearchExecutor(
        search.SearchPlan("query", mode="dense", top_k=2, namespace="default", scope_ids=["scope_alpha"]),
        store=backend_store,
    ).execute()

    assert [item["id"] for item in results] == ["common-high", "scoped-low"]


def test_hybrid_fuses_dense_and_sparse_without_dense_score_filter(monkeypatch):
    import search

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            return [(Document(page_content="dense 低相关结果", metadata={}, id="dense-low"), 0.34)]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type), lambda collection_type, metadata_filter: [
        {"id": "sparse-hit", "content": "八百 B 精确命中", "metadata": {}, "collection_type": collection_type},
    ])

    results = search._SearchExecutor(
        search.SearchPlan("八百b", mode="hybrid", top_k=5, namespace="default"),
        sparse=ReadyMemorySparse(),
        store=backend_store,
    ).execute()

    assert {item["id"] for item in results} == {"dense-low", "sparse-hit"}


def test_hybrid_retrieves_dense_and_sparse_in_parallel(monkeypatch):
    import search

    active_calls = 0
    max_active_calls = 0
    guard = threading.Lock()

    def enter_call():
        nonlocal active_calls, max_active_calls
        with guard:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)

    def leave_call():
        nonlocal active_calls
        with guard:
            active_calls -= 1

    def fake_retrieve_dense(store, collection_type, metadata_filter, query, limit):
        enter_call()
        time.sleep(0.05)
        leave_call()
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "collection_type": collection_type, "_score": 0.8}]

    def fake_retrieve_sparse(store, collection_type, metadata_filter, query, limit, sparse=None):
        enter_call()
        time.sleep(0.05)
        leave_call()
        return [{"id": "sparse-1", "content": "sparse", "metadata": {}, "collection_type": collection_type, "_score": 1.2}]

    monkeypatch.setattr(search, "_retrieve_dense", fake_retrieve_dense)
    monkeypatch.setattr(search, "_retrieve_sparse", fake_retrieve_sparse)

    executor = search._SearchExecutor(search.SearchPlan("query", mode="hybrid", top_k=5), store=FakeBackendStore())
    results = executor._retrieve_collection("common", ("common-filter", "default"), 5)

    assert {item["id"] for item in results} == {"dense-1", "sparse-1"}
    assert max_active_calls == 2


def test_sparse_store_mode_uses_qdrant_sparse_store(monkeypatch):
    import search

    calls = []

    class StoreSparse(SparseEmbeddings):
        ready = True

        def embed_query(self, text):
            return SparseVector(indices=[1], values=[1.0])

        def embed_documents(self, texts):
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeStore:
        def similarity_search_with_score(self, query, k, filter):
            calls.append(("qdrant", query, k, filter))
            return [(Document(page_content="store sparse result", metadata={}, id="sparse-store-1"), 1.0)]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore())

    results = search._retrieve_sparse(backend_store, "common", ("common-filter", "default"), "query", 5, StoreSparse())

    assert calls == [("qdrant", "query", 5, ("common-filter", "default"))]
    assert results[0]["id"] == "sparse-store-1"


def test_memory_sparse_requires_startup_sparse_component(monkeypatch):
    import search

    backend_store = FakeBackendStore()

    with pytest.raises(RuntimeError, match="sparse is not initialized"):
        search._retrieve_sparse(backend_store, "common", ("common-filter", "default"), "query", 5, sparse=None)


def test_hybrid_store_sparse_fuses_dense_and_sparse_with_plan_weights(monkeypatch):
    import search

    calls = []

    class StoreSparse(SparseEmbeddings):
        ready = True

        def embed_query(self, text):
            return SparseVector(indices=[1], values=[1.0])

        def embed_documents(self, texts):
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeStore:
        def __init__(self, mode):
            self.mode = mode

        def similarity_search_with_score(self, query, k, filter):
            calls.append((self.mode, query, k, filter))
            return [(Document(page_content=f"{self.mode} result", metadata={}, id=f"{self.mode}-store-1"), 1.0)]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(mode))

    executor = search._SearchExecutor(
        search.SearchPlan("query", mode="hybrid", top_k=5, dense_weight=0.0, sparse_weight=1.0, rrf_k=1),
        sparse=StoreSparse(),
        store=backend_store,
    )
    results = executor._retrieve_collection("common", ("common-filter", "default"), 5)

    assert sorted(calls) == [
        ("dense", "query", 5, ("common-filter", "default")),
        ("sparse", "query", 5, ("common-filter", "default")),
    ]
    assert [item["id"] for item in results] == ["sparse-store-1", "dense-store-1"]


def test_rerank_receives_dense_candidates_without_dense_score_filter(monkeypatch):
    import search

    class FakeStore:
        def __init__(self, collection_type):
            self.collection_type = collection_type

        def similarity_search_with_score(self, query, k, filter):
            if self.collection_type == "common":
                return [(Document(page_content="低相关通用", metadata={}, id="common-low"), 0.34)]
            return [(Document(page_content="高相关专属", metadata={}, id="scoped-high"), 0.62)]

    received = {}

    class FakeRerank:
        ready = True

        def start(self):
            pass

        def stop(self):
            pass

        def rerank(self, query, items, top_k):
            received["ids"] = [item["id"] for item in items]
            return items[:top_k]

    backend_store = FakeBackendStore(lambda collection_type, mode: FakeStore(collection_type), total_chunks=2)

    results = search._SearchExecutor(
        search.SearchPlan("年检", mode="hybrid", top_k=5, rerank=True, fetch_k=10, namespace="default", scope_ids=["scope_alpha"]),
        rerank=FakeRerank(),
        sparse=ReadyMemorySparse(),
        store=backend_store,
    ).execute()

    assert received["ids"] == ["scoped-high", "common-low"]
    assert [item["id"] for item in results] == ["scoped-high", "common-low"]
