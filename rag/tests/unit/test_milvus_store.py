from concurrent.futures import ThreadPoolExecutor
import time

import pytest


pytestmark = pytest.mark.unit


class FakeDense:
    ready = True

    def __init__(self):
        self.queries = []
        self.documents = []

    def start(self):
        pass

    def embed_query(self, query):
        self.queries.append(query)
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeMilvusClient:
    instances = []

    def __init__(self, uri, timeout=None):
        self.uri = uri
        self.timeout = timeout
        self.collections = set()
        self.created = []
        self.loaded = []
        self.inserted = []
        self.deleted = []
        self.flushed = []
        self.searches = []
        self.hybrid_searches = []
        self.queries = []
        self.closed = False
        FakeMilvusClient.instances.append(self)

    @classmethod
    def create_schema(cls, **kwargs):
        return FakeSchema(**kwargs)

    @classmethod
    def prepare_index_params(cls, field_name="", **kwargs):
        return FakeIndexParams(field_name, kwargs)

    def has_collection(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, **kwargs):
        self.collections.add(kwargs["collection_name"])
        self.created.append(kwargs)

    def load_collection(self, collection_name, timeout=None):
        self.loaded.append((collection_name, timeout))

    def insert(self, collection_name, data, timeout=None):
        self.inserted.append((collection_name, data, timeout))

    def search(self, collection_name, **kwargs):
        self.searches.append((collection_name, kwargs))
        return [[{"id": "pk1", "distance": 0.25, "entity": {"pk": "pk1", "text": "hello", "file_id": "file1"}}]]

    def hybrid_search(self, collection_name, **kwargs):
        self.hybrid_searches.append((collection_name, kwargs))
        return [[{"id": "pk1", "distance": 1.0, "entity": {"pk": "pk1", "text": "hello", "file_id": "file1"}}]]

    def query(self, collection_name, **kwargs):
        self.queries.append((collection_name, kwargs))
        if kwargs.get("output_fields") == ["count(*)"]:
            return [{"count(*)": 2}]
        if kwargs.get("output_fields") == ["pk"]:
            return [{"pk": "pk1"}]
        if hasattr(self, "query_rows"):
            rows = self.query_rows[min(len(self.queries) - 1, len(self.query_rows) - 1)]
            return rows
        return [{"pk": "pk1", "text": "hello", "file_id": "file1", "filename": "a.txt", "chunk_index": 0}]

    def delete(self, collection_name, ids, timeout=None):
        self.deleted.append((collection_name, ids, timeout))

    def flush(self, collection_name, timeout=None):
        self.flushed.append((collection_name, timeout))

    def drop_collection(self, collection_name):
        self.collections.discard(collection_name)

    def close(self):
        self.closed = True


class FakeSchema:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fields = []
        self.functions = []

    def add_field(self, **kwargs):
        self.fields.append(kwargs)

    def add_function(self, function):
        self.functions.append(function)


class FakeIndexParams:
    def __init__(self, field_name, kwargs):
        self.field_name = field_name
        self.kwargs = kwargs
        self.indexes = []

    def add_index(self, **kwargs):
        self.indexes.append(kwargs)


def _started_store(client=None, dense=None, sparse=None, uri="http://localhost:19530", timeout=None, parallel=False):
    from rag.store.milvus import MilvusStore

    store = MilvusStore(
        dense=dense or FakeDense(),
        sparse=sparse,
        uri=uri,
        timeout=timeout,
        parallel_sparse_embedding=parallel,
    )
    store.client = client
    store.start()
    return store


def _store_sparse():
    from rag.sparse.milvus_bge_m3 import MilvusBGEM3Sparse

    class FakeStoreSparse(MilvusBGEM3Sparse):
        ready = True

        def __init__(self):
            pass

        def start(self):
            pass

        def embed_query(self, query):
            return {1: 1.0}

        def embed_documents(self, texts):
            return [{1: 1.0} for _ in texts]

    return FakeStoreSparse()


def _builtin_bm25_sparse():
    from rag.sparse.milvus_bm25 import MilvusBM25Sparse

    sparse = MilvusBM25Sparse()
    sparse.start()
    return sparse


def test_milvus_store_resolves_local_lite_uri_from_project_root(tmp_path):
    from rag.store import milvus

    project_root = tmp_path / "rag"
    backend_dir = project_root / "backend"
    backend_dir.mkdir(parents=True)

    uri = milvus._connection_uri("milvus_data/lite/lite.db", project_root=project_root)

    assert uri == str(project_root / "milvus_data" / "lite" / "lite.db")
    assert (project_root / "milvus_data" / "lite").is_dir()


def test_milvus_store_keeps_remote_uri_unchanged():
    from rag.store import milvus

    assert milvus._connection_uri("http://localhost:19530") == "http://localhost:19530"


def test_milvus_store_initializes_one_native_client_for_store_sparse(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    store = _started_store(sparse=_store_sparse())
    store.ensure_app_collection("imsdom")

    assert store.sparse_uses_store()
    assert len(FakeMilvusClient.instances) == 1
    assert FakeMilvusClient.instances[0].created[0]["collection_name"] == "imsdom_chunks"


def test_milvus_store_passes_timeout_to_native_client(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    store = _started_store(timeout=30)
    store.ensure_app_collection("imsdom")

    assert FakeMilvusClient.instances[0].timeout == 30


def test_milvus_ensure_app_collection_retries_when_service_is_not_ready(monkeypatch):
    attempts = {"count": 0}
    sleeps = []

    class FlakyMilvusClient(FakeMilvusClient):
        def has_collection(self, collection_name):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("milvus not ready")
            return super().has_collection(collection_name)

    monkeypatch.setattr("pymilvus.MilvusClient", FlakyMilvusClient)
    monkeypatch.setattr("rag.store.startup.time.sleep", lambda seconds: sleeps.append(seconds))

    store = _started_store()
    store.ensure_app_collection("imsdom")

    assert attempts["count"] == 2
    assert sleeps == [1]
    assert store.ready is True


def test_milvus_store_uses_builtin_function_as_store_sparse():
    store = _started_store(sparse=_builtin_bm25_sparse())

    assert store.sparse_uses_store()


def test_milvus_stop_closes_native_client():
    client = FakeMilvusClient("http://localhost:19530")
    store = _started_store(client=client)

    store.stop()

    assert client.closed is True
    assert store.client is None


def test_milvus_stop_releases_local_lite_server(monkeypatch):
    from rag.store import milvus

    released = []

    monkeypatch.setattr(milvus, "_connection_uri", lambda uri: "/tmp/rag/milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_release_lite_server", lambda uri: released.append(uri))

    store = _started_store(uri="milvus_data/lite/lite.db")
    store.stop()

    assert released == ["/tmp/rag/milvus_data/lite/lite.db"]


def test_milvus_stop_does_not_release_standalone_server(monkeypatch):
    from rag.store import milvus

    released = []
    monkeypatch.setattr(milvus, "_release_lite_server", lambda uri: released.append(uri))

    store = _started_store(uri="http://localhost:19530")
    store.stop()

    assert released == []


def test_milvus_drop_collections_keeps_local_lite_server(monkeypatch):
    released = []
    client = FakeMilvusClient("milvus_data/lite/lite.db")
    client.collections.add("imsdom_chunks")
    monkeypatch.setattr("rag.store.milvus._release_lite_server", lambda uri: released.append(uri))

    store = _started_store(client=client, uri="milvus_data/lite/lite.db")
    with store.app_context("imsdom"):
        store.drop_collections()

    assert released == []
    assert "imsdom_chunks" not in client.collections


def test_milvus_search_and_query_use_configured_timeout():
    from rag.scope import app_collection

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    store = _started_store(client=client, sparse=_store_sparse(), timeout=30)

    with app_collection("imsdom"):
        store.search_dense("query", 5, "file_id in ['file_a']")
        store.get_search_documents("file_id in ['file_a']")

    assert client.searches[0][1]["timeout"] == 30
    assert client.queries[0][1]["timeout"] == 30


def test_milvus_get_total_chunks_uses_count_query_with_non_empty_filter():
    from rag.scope import app_collection

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    store = _started_store(client=client, timeout=30)

    with app_collection("imsdom"):
        total = store.get_total_chunks()

    assert total == 2
    assert client.queries[0][0] == "imsdom_chunks"
    assert client.queries[0][1]["filter"] == 'pk != ""'
    assert client.queries[0][1]["output_fields"] == ["count(*)"]
    assert "limit" not in client.queries[0][1]


def test_milvus_get_total_chunks_with_file_ids_uses_file_filter():
    from rag.scope import app_collection

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    store = _started_store(client=client, timeout=30)

    with app_collection("imsdom"):
        total = store.get_total_chunks(["file-a"])

    assert total == 2
    assert client.queries[0][1]["filter"] == "file_id in ['file-a']"
    assert client.queries[0][1]["output_fields"] == ["count(*)"]


def test_milvus_list_chunks_uses_keyset_cursor():
    from rag.scope import app_collection

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    client.query_rows = [
        [
            {"pk": "pk1", "text": "hello", "file_id": "file-a", "filename": "a.txt", "chunk_index": 0},
            {"pk": "pk2", "text": "world", "file_id": "file-a", "filename": "a.txt", "chunk_index": 1},
        ],
        [{"pk": "pk2", "text": "world", "file_id": "file-a", "filename": "a.txt", "chunk_index": 1}],
    ]
    store = _started_store(client=client, timeout=30)

    with app_collection("imsdom"):
        first_page = store.list_chunks(file_ids=["file-a"], limit=1)
        page = store.list_chunks(file_ids=["file-a"], limit=2, cursor=first_page["next_cursor"])

    assert [document["id"] for document in page["documents"]] == ["pk2"]
    assert page["next_cursor"] is None
    assert page["has_more"] is False
    assert client.queries[0][0] == "imsdom_chunks"
    assert client.queries[0][1]["filter"] == "file_id in ['file-a']"
    assert client.queries[0][1]["limit"] == 2
    assert client.queries[0][1]["order_by"] == [
        "file_id:asc",
        "chunk_index:asc",
        "pk:asc",
    ]
    assert "offset" not in client.queries[0][1]
    assert "chunk_index > 0" in client.queries[1][1]["filter"]
    assert client.queries[1][1]["limit"] == 3
    assert client.queries[1][1]["order_by"] == client.queries[0][1]["order_by"]
    assert "offset" not in client.queries[1][1]
    assert client.queries[0][1]["timeout"] == 30


def test_milvus_store_uses_ip_metric_for_embedding_sparse_and_bm25_metric_for_builtin_sparse():
    store = _started_store(sparse=_store_sparse())
    assert store._search_params_for_mode("sparse") == {"metric_type": "IP", "params": {}}
    assert store._search_params_for_mode("hybrid")[1] == {"metric_type": "IP", "params": {}}

    store = _started_store(sparse=_builtin_bm25_sparse())
    assert store._search_params_for_mode("sparse") == {"metric_type": "BM25", "params": {}}
    assert store._search_params_for_mode("hybrid")[1] == {"metric_type": "BM25", "params": {}}


def test_milvus_lite_uses_flat_dense_index_to_avoid_hnsw_faiss_background_build():
    store = _started_store(uri="milvus_data/lite/lite.db")
    assert store._index_params_for_mode("dense") == {"metric_type": "COSINE", "index_type": "FLAT", "params": {}}

    store = _started_store(uri="milvus_data/lite/lite.db", sparse=_store_sparse())
    assert store._index_params_for_mode("hybrid") == [
        {"metric_type": "COSINE", "index_type": "FLAT", "params": {}},
        {"metric_type": "IP", "index_type": "SPARSE_INVERTED_INDEX", "params": {"drop_ratio_build": 0.2}},
    ]

    store = _started_store(uri="milvus_data/lite/lite.db", sparse=_builtin_bm25_sparse())
    assert store._index_params_for_mode("hybrid") == [
        {"metric_type": "COSINE", "index_type": "FLAT", "params": {}},
        {
            "metric_type": "BM25",
            "index_type": "SPARSE_INVERTED_INDEX",
            "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
        },
    ]


def test_milvus_store_uses_cosine_metric_for_dense_vectors():
    store = _started_store()

    assert store._search_params_for_mode("dense") == {"metric_type": "COSINE", "params": {}}
    assert store._search_params_for_mode("hybrid")[0] == {"metric_type": "COSINE", "params": {}}
    assert store._index_params_for_mode("dense") == {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}}


def test_milvus_hybrid_uses_app_rrf_instead_of_native_hybrid_search():
    from rag.scope import app_collection

    class HybridClient(FakeMilvusClient):
        def search(self, collection_name, **kwargs):
            self.searches.append((collection_name, kwargs))
            if kwargs["anns_field"] == "dense":
                return [[
                    {"id": "dense-only", "distance": 0.9, "entity": {"pk": "dense-only", "text": "dense", "file_id": "file1"}},
                    {"id": "both", "distance": 0.8, "entity": {"pk": "both", "text": "both", "file_id": "file1"}},
                ]]
            return [[
                {"id": "both", "distance": 1.0, "entity": {"pk": "both", "text": "both", "file_id": "file1"}},
                {"id": "sparse-only", "distance": 0.7, "entity": {"pk": "sparse-only", "text": "sparse", "file_id": "file1"}},
            ]]

    client = HybridClient("http://localhost:19530", timeout=30)
    store = _started_store(client=client, sparse=_store_sparse(), timeout=30)

    with app_collection("imsdom"):
        results = store.search_hybrid("query", 2, "", dense_weight=0.5, sparse_weight=0.5, rrf_k=60)

    assert client.hybrid_searches == []
    assert [call[1]["anns_field"] for call in client.searches] == ["dense", "sparse"]
    assert [item["id"] for item in results] == ["both", "dense-only"]


def test_milvus_add_file_chunks_serializes_same_file_writes():
    from rag.scope import app_collection

    events = []

    class SlowDeleteClient(FakeMilvusClient):
        def query(self, collection_name, **kwargs):
            if kwargs.get("output_fields") == ["pk"]:
                events.append("delete")
                time.sleep(0.05)
                return []
            return super().query(collection_name, **kwargs)

        def insert(self, collection_name, data, timeout=None):
            events.append("insert")
            return super().insert(collection_name, data, timeout)

        def flush(self, collection_name, timeout=None):
            events.append("flush")
            return super().flush(collection_name, timeout)

    client = SlowDeleteClient("http://localhost:19530", timeout=30)
    store = _started_store(client=client, timeout=30)
    chunks = [{"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}}]

    def add_chunks():
        with app_collection("imsdom"):
            return store.add_file_chunks(chunks, "file-a")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(add_chunks) for _ in range(2)]
        [future.result() for future in futures]

    assert events == ["delete", "insert", "flush", "delete", "insert", "flush"]


def test_milvus_builtin_bm25_hybrid_declares_dense_and_sparse_vector_fields():
    store = _started_store(sparse=_builtin_bm25_sparse())

    assert store._vector_field_for_mode("hybrid") == ["dense", "sparse"]


def test_milvus_standalone_uses_explicit_native_index_params():
    store = _started_store(uri="http://localhost:19530")

    assert store._index_params_for_mode("dense") == {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}}


def test_milvus_ensure_app_collection_creates_collection_without_placeholder_documents(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    store = _started_store(uri="http://localhost:19530")
    store.ensure_app_collection("imsdom")

    client = FakeMilvusClient.instances[0]
    assert client.collections == {"imsdom_chunks"}
    assert client.created[0]["collection_name"] == "imsdom_chunks"
    indexed_fields = {index["field_name"] for index in client.created[0]["index_params"].indexes}
    assert {"file_id", "chunk_index"} <= indexed_fields
    assert client.inserted == []


def test_milvus_add_file_chunks_inserts_native_rows():
    from rag.scope import app_collection
    from rag.store import milvus

    client = FakeMilvusClient("http://localhost:19530")
    store = _started_store(client=client)

    with app_collection("imsdom"):
        count = store.add_file_chunks([
            {"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}},
        ], "file1")

    assert count == 1
    assert client.inserted[0][0] == "imsdom_chunks"
    assert client.inserted[0][1][0]["pk"] == milvus._point_id("chunk-a")
    assert client.inserted[0][1][0]["text"] == "hello"
    assert client.inserted[0][1][0]["file_id"] == "file1"
    assert client.inserted[0][1][0]["vector"] == [0.1, 0.2, 0.3]
    assert client.flushed[-1] == ("imsdom_chunks", None)
