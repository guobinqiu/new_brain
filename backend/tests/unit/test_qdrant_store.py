import pytest
from qdrant_client.http.models import SparseVector


pytestmark = pytest.mark.unit


def test_add_file_chunks_writes_file_metadata(monkeypatch):
    import store

    calls = []

    class FakeDense:
        def embed_documents(self, texts):
            calls.append(("embed", texts))
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeClient:
        def upsert(self, **kwargs):
            calls.append(("upsert", kwargs["collection_name"], kwargs["points"]))

    monkeypatch.setattr(store, "_require_search_ready", lambda: calls.append(("ready",)))
    monkeypatch.setattr(store, "delete_file_chunks", lambda file_id: calls.append(("delete", file_id)) or 2)
    monkeypatch.setattr(store, "_get_dense", lambda: FakeDense())
    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    chunks = [
        {"id": "chunk-1", "content": "华为给我们一万六千张卡", "metadata": {"filename": "liang.pdf", "chunk_index": 0}},
    ]

    assert store.add_file_chunks(chunks, file_id="550e8400e29b41d4a716446655440000") == 1
    assert calls[0] == ("ready",)
    assert calls[1] == ("delete", "550e8400e29b41d4a716446655440000")

    _, collection_name, points = calls[3]
    assert collection_name == store.QDRANT_CHUNKS_COLLECTION
    assert points[0].id == store._point_id("chunk-1")
    assert points[0].payload["content"] == "华为给我们一万六千张卡"
    assert points[0].payload["metadata"]["file_id"] == "550e8400e29b41d4a716446655440000"
    assert points[0].payload["metadata"]["chunk_index"] == 0
    assert points[0].payload["metadata"]["filename"] == "liang.pdf"


def test_ensure_payload_indexes_only_creates_file_id_index(monkeypatch):
    import store

    calls = []

    class FakeClient:
        def create_payload_index(self, **kwargs):
            calls.append((kwargs["collection_name"], kwargs["field_name"]))

    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.ensure_payload_indexes()

    assert calls == [(store.QDRANT_CHUNKS_COLLECTION, "metadata.file_id")]


def test_add_file_chunks_writes_sparse_vector_when_sparse_vectors_are_stored(monkeypatch):
    import store
    from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    calls = []

    class FakeDense:
        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeSparse(QdrantBGEM3Sparse):
        def __init__(self):
            pass

        def embed_documents(self, texts):
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeClient:
        def upsert(self, **kwargs):
            calls.append(("upsert", kwargs["points"]))

    monkeypatch.setattr(store, "_require_search_ready", lambda: None)
    monkeypatch.setattr(store, "_sparse_uses_store", lambda: True)
    monkeypatch.setattr(store, "delete_file_chunks", lambda file_id: None)
    monkeypatch.setattr(store, "_get_dense", lambda: FakeDense())
    monkeypatch.setattr(store, "_get_sparse", lambda: FakeSparse())
    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    chunks = [
        {"id": "chunk-1", "content": "通用知识", "metadata": {"filename": "faq.pdf", "chunk_index": 0}},
    ]

    assert store.add_file_chunks(chunks, file_id="file_a") == 1
    point = calls[0][1][0]
    assert "dense" in point.vector
    assert "sparse" in point.vector
    assert point.vector["sparse"].indices == [1]


def test_add_file_chunks_requires_file_id():
    import store

    with pytest.raises(ValueError, match="file_id"):
        store.add_file_chunks([{"id": "chunk-1", "content": "x", "metadata": {"filename": "x.txt", "chunk_index": 0}}], file_id="")


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


def test_qdrant_client_uses_configured_timeout(monkeypatch):
    import store

    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(store, "QdrantClient", FakeClient)
    store.close_store()
    try:
        store._configure_store(url="http://localhost:6333", timeout=30)
        store.get_qdrant_client()
    finally:
        store.close_store()

    assert created[0]["timeout"] == 30


def test_init_store_retries_when_qdrant_is_not_ready(monkeypatch):
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

    attempts = {"count": 0}

    def flaky_ensure_collections():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("qdrant not ready")
        calls.append(("ensure", attempts["count"]))

    monkeypatch.setattr(store, "ensure_collections", flaky_ensure_collections)
    monkeypatch.setattr("store.startup.time.sleep", lambda seconds: calls.append(("sleep", seconds)))

    store.init_store(dense=FakeDense())

    assert attempts["count"] == 2
    assert ("sleep", 1) in calls
    assert store.is_search_ready() is True


def test_init_store_loads_model_probes_size_and_ensures_collection(monkeypatch):
    import store

    calls = []

    class FakeDense:
        ready = True

        def start(self):
            raise AssertionError("store must not start dense")

        def stop(self):
            self.ready = False

        def embed_query(self, text):
            calls.append(("probe", text))
            return [0.1, 0.2, 0.3]

        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeClient:
        def collection_exists(self, collection_name):
            calls.append(("exists", collection_name))
            return True

        def create_payload_index(self, **kwargs):
            calls.append(("payload_index", kwargs["collection_name"], kwargs["field_name"]))

    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.init_store(dense=FakeDense())

    assert store.is_search_ready() is True
    assert calls.count(("probe", "dimension probe")) == 1
    assert ("exists", store.QDRANT_CHUNKS_COLLECTION) in calls
    assert ("payload_index", store.QDRANT_CHUNKS_COLLECTION, "metadata.file_id") in calls


def test_init_store_creates_sparse_vector_config_when_sparse_uses_store(monkeypatch):
    import store
    from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

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

    class FakeSparse(QdrantBGEM3Sparse):
        ready = True

        def __init__(self):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def embed_query(self, text):
            return SparseVector(indices=[1], values=[1.0])

        def embed_documents(self, texts):
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeClient:
        def collection_exists(self, collection_name):
            return False

        def create_collection(self, **kwargs):
            calls.append(("create", kwargs["collection_name"], kwargs.get("sparse_vectors_config")))

        def get_collection(self, collection_name):
            return object()

        def create_payload_index(self, **kwargs):
            pass

    sparse = FakeSparse()
    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.init_store(dense=FakeDense(), sparse=sparse)

    assert any(call[0] == "create" and "sparse" in call[2] for call in calls)
