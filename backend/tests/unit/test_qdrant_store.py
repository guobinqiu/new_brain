import pytest
from langchain_qdrant.sparse_embeddings import SparseEmbeddings, SparseVector


pytestmark = pytest.mark.unit


def test_add_common_documents_deletes_then_inserts_with_namespace(monkeypatch):
    import store

    calls = []

    class FakeStore:
        def add_documents(self, documents, ids):
            calls.append(("add", documents, ids))

    monkeypatch.setattr(store, "_require_search_ready", lambda: calls.append(("ready",)))
    monkeypatch.setattr(store, "delete_common_document", lambda filename, namespace="default": calls.append(("delete", filename, namespace)) or 2)
    monkeypatch.setattr(store, "_common_store", lambda mode="hybrid": FakeStore())

    chunks = [
        {"id": "chunk-1", "content": "通用知识", "metadata": {"filename": "faq.pdf", "chunk_index": 0}},
    ]

    assert store.add_common_documents(chunks, namespace="tenant_a") == 1
    assert calls[0] == ("ready",)
    assert calls[1] == ("delete", "faq.pdf", "tenant_a")

    _, documents, ids = calls[2]
    assert ids == [store._point_id("chunk-1")]
    assert documents[0].page_content == "通用知识"
    assert documents[0].metadata["namespace"] == "tenant_a"
    assert documents[0].metadata["filename"] == "faq.pdf"
    assert documents[0].metadata["source_id"] == "chunk-1"


def test_add_common_documents_uses_hybrid_store_when_sparse_vectors_are_stored(monkeypatch):
    import store

    calls = []

    class FakeStore:
        def add_documents(self, documents, ids):
            calls.append(("add", documents, ids))

    monkeypatch.setattr(store, "_require_search_ready", lambda: None)
    monkeypatch.setattr(store, "_sparse_uses_store", lambda: True)
    monkeypatch.setattr(store, "delete_common_document", lambda filename, namespace="default": None)
    monkeypatch.setattr(store, "_common_store", lambda mode="hybrid": calls.append(("store", mode)) or FakeStore())

    chunks = [
        {"id": "chunk-1", "content": "通用知识", "metadata": {"filename": "faq.pdf", "chunk_index": 0}},
    ]

    assert store.add_common_documents(chunks, namespace="tenant_a") == 1
    assert ("store", "hybrid") in calls


def test_add_scoped_documents_deletes_then_inserts_with_scope(monkeypatch):
    import store

    calls = []

    class FakeStore:
        def add_documents(self, documents, ids):
            calls.append(("add", documents, ids))

    monkeypatch.setattr(store, "_require_search_ready", lambda: calls.append(("ready",)))
    monkeypatch.setattr(store, "delete_scoped_document", lambda filename, namespace="default", scope_id=None: calls.append(("delete", filename, namespace, scope_id)) or 2)
    monkeypatch.setattr(store, "_scoped_store", lambda mode="hybrid": FakeStore())

    chunks = [
        {"id": "chunk-1", "content": "范围知识", "metadata": {"filename": "faq.pdf", "chunk_index": 0}},
    ]

    assert store.add_scoped_documents(chunks, namespace="tenant_a", scope_id="scope_001") == 1
    assert calls[0] == ("ready",)
    assert calls[1] == ("delete", "faq.pdf", "tenant_a", "scope_001")

    _, documents, ids = calls[2]
    assert ids == [store._point_id("chunk-1")]
    assert documents[0].metadata["namespace"] == "tenant_a"
    assert documents[0].metadata["scope_id"] == "scope_001"
    assert documents[0].metadata["filename"] == "faq.pdf"
    assert documents[0].metadata["source_id"] == "chunk-1"


def test_add_scoped_documents_uses_hybrid_store_when_sparse_vectors_are_stored(monkeypatch):
    import store

    calls = []

    class FakeStore:
        def add_documents(self, documents, ids):
            calls.append(("add", documents, ids))

    monkeypatch.setattr(store, "_require_search_ready", lambda: None)
    monkeypatch.setattr(store, "_sparse_uses_store", lambda: True)
    monkeypatch.setattr(store, "delete_scoped_document", lambda filename, namespace="default", scope_id=None: None)
    monkeypatch.setattr(store, "_scoped_store", lambda mode="hybrid": calls.append(("store", mode)) or FakeStore())

    chunks = [
        {"id": "chunk-1", "content": "范围知识", "metadata": {"filename": "faq.pdf", "chunk_index": 0}},
    ]

    assert store.add_scoped_documents(chunks, namespace="tenant_a", scope_id="scope_001") == 1
    assert ("store", "hybrid") in calls


def test_add_scoped_documents_requires_scope_id():
    import store

    with pytest.raises(ValueError, match="scope_id"):
        store.add_scoped_documents([], namespace="tenant_a", scope_id="")


def test_document_key_distinguishes_common_and_scoped_documents():
    import store

    assert store._document_key("common", "tenant_a", None, "faq.pdf") == "common:tenant_a::faq.pdf"
    assert store._document_key("scoped", "tenant_a", "scope_001", "faq.pdf") == "scoped:tenant_a:scope_001:faq.pdf"


def test_point_id_maps_arbitrary_chunk_id_to_uuid():
    import uuid
    import store

    point_id = store._point_id("test_ai.txt_0_a836bd2b")

    assert str(uuid.UUID(point_id)) == point_id
    assert store._point_id("test_ai.txt_0_a836bd2b") == point_id


def test_get_dense_requires_explicit_store_initialization():
    import store

    with pytest.raises(RuntimeError, match="search is not initialized"):
        store._get_dense()


def test_get_dense_vector_size_requires_explicit_store_initialization():
    import store

    with pytest.raises(RuntimeError, match="search is not initialized"):
        store._get_dense_vector_size()


def test_store_for_requires_store_prepared_during_initialization(monkeypatch):
    import store

    monkeypatch.setattr(store, "_ready", True)
    store._stores.clear()

    with pytest.raises(RuntimeError, match="store is not initialized"):
        store._store_for("common", "dense")


def test_init_store_loads_model_probes_size_and_prepares_stores(monkeypatch):
    import store

    calls = []

    class FakeDense:
        ready = False

        def start(self):
            calls.append(("load", store.DENSE_MODEL_DIR))
            self.ready = True

        def stop(self):
            self.ready = False

        def embed_query(self, text):
            calls.append(("probe", text))
            return [0.1, 0.2, 0.3]

        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeQdrantStore:
        def __init__(self, **kwargs):
            calls.append(("store", kwargs["collection_name"], kwargs["retrieval_mode"]))

    class FakeClient:
        def collection_exists(self, collection_name):
            calls.append(("exists", collection_name))
            return True

        def create_payload_index(self, **kwargs):
            calls.append(("payload_index", kwargs["collection_name"], kwargs["field_name"]))

    monkeypatch.setattr(store, "QdrantVectorStore", FakeQdrantStore)
    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.init_store(dense=FakeDense())

    assert store.is_search_ready() is True
    assert calls.count(("load", store.DENSE_MODEL_DIR)) == 1
    assert calls.count(("probe", "dimension probe")) == 1
    assert ("store", store.QDRANT_COMMON_COLLECTION, store.RetrievalMode.DENSE) in calls
    assert ("store", store.QDRANT_SCOPED_COLLECTION, store.RetrievalMode.DENSE) in calls


def test_init_store_prepares_sparse_and_hybrid_stores_when_sparse_uses_store(monkeypatch):
    import store

    calls = []

    class FakeDense:
        ready = True

        def start(self):
            pass

        def stop(self):
            pass

        def embed_query(self, text):
            return [0.1, 0.2, 0.3]

        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeSparse(SparseEmbeddings):
        ready = True

        def start(self):
            pass

        def stop(self):
            pass

        def embed_query(self, text):
            return SparseVector(indices=[1], values=[1.0])

        def embed_documents(self, texts):
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeQdrantStore:
        def __init__(self, **kwargs):
            calls.append(("store", kwargs["collection_name"], kwargs["retrieval_mode"], kwargs.get("sparse_embedding"), kwargs.get("sparse_vector_name")))

    class FakeClient:
        def collection_exists(self, collection_name):
            return False

        def create_collection(self, **kwargs):
            calls.append(("create", kwargs["collection_name"], kwargs.get("sparse_vectors_config")))

        def create_payload_index(self, **kwargs):
            pass

    sparse = FakeSparse()
    monkeypatch.setattr(store, "QdrantVectorStore", FakeQdrantStore)
    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.init_store(dense=FakeDense(), sparse=sparse)

    assert ("store", store.QDRANT_COMMON_COLLECTION, store.RetrievalMode.SPARSE, sparse, "sparse") in calls
    assert ("store", store.QDRANT_COMMON_COLLECTION, store.RetrievalMode.HYBRID, sparse, "sparse") in calls
    assert any(call[0] == "create" and "sparse" in call[2] for call in calls)
