import pytest
from qdrant_client.http.models import SparseVector


pytestmark = pytest.mark.unit


def test_add_file_chunks_writes_file_metadata(monkeypatch):
    import store
    from collection_names import app_collection

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

    with app_collection("imsdom"):
        assert store.add_file_chunks(chunks, file_id="550e8400-e29b-41d4-a716-446655440000") == 1
    assert calls[0] == ("ready",)
    assert calls[1] == ("delete", "550e8400-e29b-41d4-a716-446655440000")

    _, collection_name, points = calls[3]
    assert collection_name == "imsdom_chunks"
    assert points[0].id == store._point_id("chunk-1")
    assert points[0].payload["content"] == "华为给我们一万六千张卡"
    assert points[0].payload["metadata"]["file_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert points[0].payload["metadata"]["chunk_index"] == 0
    assert points[0].payload["metadata"]["filename"] == "liang.pdf"


def test_ensure_payload_indexes_creates_file_id_and_chunk_index_indexes(monkeypatch):
    import store

    calls = []

    class FakeClient:
        def create_payload_index(self, **kwargs):
            calls.append((kwargs["collection_name"], kwargs["field_name"], kwargs["field_schema"]))

    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.ensure_payload_indexes("imsdom_chunks")

    assert calls == [
        ("imsdom_chunks", "metadata.file_id", store.models.PayloadSchemaType.KEYWORD),
        ("imsdom_chunks", "metadata.chunk_index", store.models.PayloadSchemaType.INTEGER),
    ]


def test_add_file_chunks_writes_sparse_vector_when_sparse_vectors_are_stored(monkeypatch):
    import store
    from collection_names import app_collection
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

    with app_collection("imsdom"):
        assert store.add_file_chunks(chunks, file_id="file_a") == 1
    point = calls[0][1][0]
    assert "dense" in point.vector
    assert "sparse" in point.vector
    assert point.vector["sparse"].indices == [1]


def test_add_file_chunks_requires_file_id():
    import store

    with pytest.raises(ValueError, match="file_id"):
        store.add_file_chunks([{"id": "chunk-1", "content": "x", "metadata": {"filename": "x.txt", "chunk_index": 0}}], file_id="")


def test_point_id_keeps_standard_uuid_chunk_id():
    import uuid
    import store

    chunk_id = str(uuid.uuid4())
    point_id = store._point_id(chunk_id)

    assert point_id == chunk_id
    assert str(uuid.UUID(point_id)) == point_id


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


def test_qdrant_list_chunks_uses_scroll_cursor(monkeypatch):
    import store
    from collection_names import app_collection

    calls = []

    class FakeRecord:
        def __init__(self, point_id, chunk_index):
            self.id = point_id
            self.payload = {
                "content": f"chunk text {chunk_index}",
                "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": chunk_index},
            }

    class FakeClient:
        def scroll(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return [FakeRecord("point-1", 0), FakeRecord("point-2", 1)], None
            return [FakeRecord("point-2", 1)], None

    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    with app_collection("imsdom"):
        first_page = store.list_chunks(file_ids=["file-a"], limit=1)
        page = store.list_chunks(file_ids=["file-a"], limit=2, cursor=first_page["next_cursor"])

    assert page["documents"][0]["id"] == "point-2"
    assert page["next_cursor"] is None
    assert page["has_more"] is False
    assert calls[0]["collection_name"] == "imsdom_chunks"
    assert calls[0]["limit"] == 2
    assert calls[0]["order_by"] == "metadata.chunk_index"
    assert calls[0]["offset"] is None
    assert calls[1]["limit"] == 3
    assert calls[1]["order_by"] == "metadata.chunk_index"
    assert calls[1]["offset"] is None
    assert calls[1]["scroll_filter"].must[1].range.gt == 0
    assert calls[0]["with_vectors"] is False


def test_init_store_does_not_create_collection(monkeypatch):
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

    monkeypatch.setattr(store, "ensure_collections", lambda collection_name=None: calls.append(("ensure", collection_name)))

    store.init_store(dense=FakeDense())

    assert store.is_search_ready() is True
    assert calls == []


def test_init_store_loads_model_and_probes_size(monkeypatch):
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
    assert all(call[0] != "exists" for call in calls)
    assert all(call[0] != "payload_index" for call in calls)


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

        def count(self, **kwargs):
            return object()

        def create_payload_index(self, **kwargs):
            pass

    sparse = FakeSparse()
    monkeypatch.setattr(store, "get_qdrant_client", lambda: FakeClient())

    store.init_store(dense=FakeDense(), sparse=sparse)
    store.ensure_collections("imsdom_chunks")

    assert any(call[0] == "create" and "sparse" in call[2] for call in calls)
