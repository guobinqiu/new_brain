import pytest
from qdrant_client.http.models import SparseVector


pytestmark = pytest.mark.unit


class FakeDense:
    ready = True

    def __init__(self):
        self.queries = []
        self.documents = []

    def embed_query(self, text):
        self.queries.append(text)
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeCount:
    count = 0


def _chunk(chunk_id="chunk-1", content="通用知识"):
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {"filename": "faq.pdf", "chunk_index": 0},
    }


def _started_store(client, dense=None, sparse=None, parallel=False):
    from rag.store.qdrant import QdrantStore

    store = QdrantStore(dense=dense or FakeDense(), sparse=sparse, parallel_sparse_embedding=parallel)
    store.client = client
    store.start()
    return store


def test_add_file_chunks_writes_file_metadata():
    from rag.scope import app_collection
    from rag.store import qdrant

    calls = []

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            calls.append(("upsert", kwargs["collection_name"], kwargs["points"]))

    store = _started_store(FakeClient())

    with app_collection("imsdom"):
        assert store.add_file_chunks([_chunk(content="华为给我们一万六千张卡")], file_id="550e8400-e29b-41d4-a716-446655440000") == 1

    _, collection_name, points = calls[0]
    assert collection_name == "imsdom_chunks"
    assert points[0].id == qdrant._point_id("chunk-1")
    assert points[0].payload["content"] == "华为给我们一万六千张卡"
    assert points[0].payload["metadata"]["file_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert points[0].payload["metadata"]["chunk_index"] == 0
    assert points[0].payload["metadata"]["filename"] == "faq.pdf"


def test_add_file_chunks_logs_backend_retriever_and_stage_fields(caplog):
    import logging
    from rag.scope import app_collection

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            pass

    store = _started_store(FakeClient())

    with caplog.at_level(logging.INFO, logger="rag.indexing"):
        with app_collection("imsdom"):
            store.add_file_chunks([_chunk(content="华为给我们一万六千张卡")], file_id="file_a")

    records = {record.event: record for record in caplog.records if hasattr(record, "event")}
    assert records["dense_embedding_start"].app_id == "imsdom"
    assert records["dense_embedding_start"].stage == "embedding"
    assert records["dense_embedding_start"].backend == "model"
    assert records["dense_embedding_start"].retriever == "dense"
    assert records["dense_embedding_done"].status == "ok"
    assert records["qdrant_upsert_start"].stage == "index"
    assert records["qdrant_upsert_start"].backend == "qdrant"
    assert records["qdrant_upsert_start"].retriever == "vector"
    assert records["qdrant_upsert_done"].status == "ok"


def test_ensure_payload_indexes_creates_file_id_and_chunk_index_indexes():
    from rag.store import qdrant

    calls = []

    class FakeClient:
        def create_payload_index(self, **kwargs):
            calls.append((kwargs["collection_name"], kwargs["field_name"], kwargs["field_schema"]))

    store = _started_store(FakeClient())
    store.ensure_payload_indexes("imsdom_chunks")

    assert calls == [
        ("imsdom_chunks", "metadata.file_id", qdrant.models.PayloadSchemaType.KEYWORD),
        ("imsdom_chunks", "metadata.chunk_index", qdrant.models.PayloadSchemaType.INTEGER),
    ]


def test_add_file_chunks_writes_sparse_vector_when_sparse_vectors_are_stored():
    from rag.scope import app_collection
    from rag.sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    calls = []

    class FakeSparse(QdrantBGEM3Sparse):
        ready = True

        def __init__(self):
            pass

        def embed_query(self, text):
            return SparseVector(indices=[1], values=[1.0])

        def embed_documents(self, texts):
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            calls.append(("upsert", kwargs["points"]))

    store = _started_store(FakeClient(), sparse=FakeSparse())

    with app_collection("imsdom"):
        assert store.add_file_chunks([_chunk()], file_id="file_a") == 1
    point = calls[0][1][0]
    assert "dense" in point.vector
    assert "sparse" in point.vector
    assert point.vector["sparse"].indices == [1]


def test_add_file_chunks_can_parallelize_dense_and_sparse_embedding():
    import threading
    from rag.scope import app_collection
    from rag.sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    sparse_started = threading.Event()
    overlaps = []

    class ParallelDense(FakeDense):
        def embed_documents(self, texts):
            overlaps.append(sparse_started.wait(timeout=0.2))
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeSparse(QdrantBGEM3Sparse):
        ready = True

        def __init__(self):
            pass

        def embed_documents(self, texts):
            sparse_started.set()
            return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            pass

    store = _started_store(FakeClient(), dense=ParallelDense(), sparse=FakeSparse(), parallel=True)

    with app_collection("imsdom"):
        assert store.add_file_chunks([_chunk()], file_id="file_a") == 1
    assert overlaps == [True]


def test_add_file_chunks_requires_file_id():
    store = _started_store(client=None)

    with pytest.raises(ValueError, match="file_id"):
        store.add_file_chunks([_chunk(content="x")], file_id="")


def test_point_id_keeps_standard_uuid_chunk_id():
    import uuid
    from rag.store import qdrant

    chunk_id = str(uuid.uuid4())
    point_id = qdrant._point_id(chunk_id)

    assert point_id == chunk_id
    assert str(uuid.UUID(point_id)) == point_id


def test_qdrant_client_uses_configured_timeout(monkeypatch):
    from rag.store import qdrant

    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(qdrant, "QdrantClient", FakeClient)

    store = qdrant.QdrantStore(dense=FakeDense(), url="http://localhost:6333", timeout=30)
    store._client()

    assert created[0]["timeout"] == 30


def test_qdrant_list_chunks_uses_stable_three_key_cursor_across_files():
    from rag.scope import app_collection

    calls = []

    class FakeRecord:
        def __init__(self, point_id, file_id, chunk_index):
            self.id = point_id
            self.payload = {
                "content": f"{file_id} chunk text {chunk_index}",
                "metadata": {"file_id": file_id, "filename": f"{file_id}.txt", "chunk_index": chunk_index},
            }

    class FakeClient:
        def scroll(self, **kwargs):
            calls.append(kwargs)
            if kwargs["offset"] is None:
                return [
                    FakeRecord("a-0", "file-a", 0),
                    FakeRecord("b-0", "file-b", 0),
                    FakeRecord("c-0", "file-c", 0),
                    FakeRecord("a-1", "file-a", 1),
                    FakeRecord("b-1", "file-b", 1),
                ], "next"
            return [
                FakeRecord("c-1", "file-c", 1),
                FakeRecord("a-2", "file-a", 2),
                FakeRecord("b-2", "file-b", 2),
                FakeRecord("c-2", "file-c", 2),
            ], None

    store = _started_store(FakeClient())

    with app_collection("imsdom"):
        first_page = store.list_chunks(limit=4)
        page = store.list_chunks(limit=4, cursor=first_page["next_cursor"])
        last_page = store.list_chunks(limit=4, cursor=page["next_cursor"])

    assert [document["id"] for document in first_page["documents"]] == ["a-0", "a-1", "a-2", "b-0"]
    assert [document["id"] for document in page["documents"]] == ["b-1", "b-2", "c-0", "c-1"]
    assert [document["id"] for document in last_page["documents"]] == ["c-2"]
    assert last_page["next_cursor"] is None
    assert last_page["has_more"] is False
    assert calls[0]["collection_name"] == "imsdom_chunks"
    assert calls[0]["limit"] == 1000
    assert "order_by" not in calls[0]
    assert calls[0]["offset"] is None
    assert calls[1]["offset"] == "next"
    assert calls[0]["with_vectors"] is False


def test_qdrant_reads_dense_and_sparse_vectors_by_chunk_id():
    from rag.scope import app_collection

    calls = []

    class Sparse:
        indices = [1, 3]
        values = [0.4, 0.2]

    class FakeRecord:
        id = "chunk-a"
        vector = {
            "dense": [0.1, 0.2],
            "sparse": Sparse(),
        }

    class FakeClient:
        def retrieve(self, **kwargs):
            calls.append(kwargs)
            return [FakeRecord()]

    store = _started_store(FakeClient())

    with app_collection("imsdom"):
        dense = store.get_dense_vector("chunk-a")
        sparse = store.get_sparse_vector("chunk-a")

    assert dense == [0.1, 0.2]
    assert sparse == {"indices": [1, 3], "values": [0.4, 0.2]}
    assert calls[0] == {
        "collection_name": "imsdom_chunks",
        "ids": ["chunk-a"],
        "with_payload": False,
        "with_vectors": True,
    }


def test_store_start_does_not_create_collection():
    dense = FakeDense()
    store = _started_store(client=None, dense=dense)

    assert store.ready is True
    assert dense.queries == ["dimension probe"]


def test_store_start_creates_sparse_vector_config_when_sparse_uses_store():
    from rag.sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    calls = []

    class FakeSparse(QdrantBGEM3Sparse):
        ready = True

        def __init__(self):
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

    store = _started_store(FakeClient(), sparse=FakeSparse())
    store.ensure_collections("imsdom_chunks")

    assert any(call[0] == "create" and "sparse" in call[2] for call in calls)


def test_qdrant_create_collection_can_enable_int8_quantization():
    from rag.schema import QdrantQuantizationConfig

    calls = []

    class FakeClient:
        def collection_exists(self, collection_name):
            return False

        def create_collection(self, **kwargs):
            calls.append(kwargs)

        def get_collection(self, collection_name):
            return object()

        def count(self, **kwargs):
            return object()

        def create_payload_index(self, **kwargs):
            pass

    store = _started_store(FakeClient())
    store.quantization = QdrantQuantizationConfig(enable=True, type="int8", quantile=0.99, always_ram=True)
    store.ensure_collections("imsdom_chunks")

    quantization = calls[0]["quantization_config"]
    assert quantization.scalar.type == "int8"
    assert quantization.scalar.quantile == 0.99
    assert quantization.scalar.always_ram is True


def test_decode_chunk_cursor_returns_sort_key_tuple():
    from rag.store.qdrant import _decode_chunk_cursor, _encode_chunk_cursor

    cursor = _encode_chunk_cursor({"id": "chunk-a", "metadata": {"file_id": "file-a", "chunk_index": 3}})

    assert _decode_chunk_cursor(cursor) == ("file-a", 3, "chunk-a")
