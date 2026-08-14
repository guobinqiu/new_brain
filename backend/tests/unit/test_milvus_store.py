import pytest


pytestmark = pytest.mark.unit


class FakeDense:
    ready = True

    def start(self):
        pass

    def embed_query(self, query):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
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
        if kwargs.get("output_fields") == ["pk"]:
            return [{"pk": "pk1"}]
        return [{"pk": "pk1", "text": "hello", "file_id": "file1", "filename": "a.txt", "chunk_index": 0}]

    def delete(self, collection_name, ids, timeout=None):
        self.deleted.append((collection_name, ids, timeout))

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


def test_milvus_store_resolves_local_lite_uri_from_project_root(tmp_path):
    from store import milvus

    project_root = tmp_path / "rag"
    backend_dir = project_root / "backend"
    backend_dir.mkdir(parents=True)

    uri = milvus._connection_uri("milvus_data/lite/lite.db", project_root=project_root)

    assert uri == str(project_root / "milvus_data" / "lite" / "lite.db")
    assert (project_root / "milvus_data" / "lite").is_dir()


def test_milvus_store_keeps_remote_uri_unchanged():
    from store import milvus

    assert milvus._connection_uri("http://localhost:19530") == "http://localhost:19530"


def test_milvus_store_initializes_one_native_client_for_store_sparse(monkeypatch):
    from store import milvus
    from sparse.milvus_bge_m3 import MilvusBGEM3Sparse

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

    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)
    milvus.close_store()
    try:
        milvus.init_store(
            dense=FakeDense(),
            sparse=FakeStoreSparse(),
            uri="http://localhost:19530",
            chunks_collection="chunks",
        )

        assert milvus._sparse_uses_store()
        assert len(FakeMilvusClient.instances) == 1
        assert FakeMilvusClient.instances[0].created[0]["collection_name"] == "chunks"
    finally:
        milvus.close_store()


def test_milvus_store_passes_timeout_to_native_client(monkeypatch):
    from store import milvus

    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)
    milvus.close_store()
    try:
        milvus.init_store(
            dense=FakeDense(),
            sparse=None,
            uri="http://localhost:19530",
            timeout=30,
            chunks_collection="chunks",
        )
    finally:
        milvus.close_store()

    assert FakeMilvusClient.instances[0].timeout == 30


def test_milvus_init_store_retries_when_service_is_not_ready(monkeypatch):
    from store import milvus

    attempts = {"count": 0}
    sleeps = []

    class FlakyMilvusClient(FakeMilvusClient):
        def has_collection(self, collection_name):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("milvus not ready")
            return super().has_collection(collection_name)

    monkeypatch.setattr("pymilvus.MilvusClient", FlakyMilvusClient)
    monkeypatch.setattr("store.startup.time.sleep", lambda seconds: sleeps.append(seconds))
    milvus.close_store()
    try:
        milvus.init_store(
            dense=FakeDense(),
            sparse=None,
            uri="http://localhost:19530",
            chunks_collection="chunks",
        )

        assert attempts["count"] == 2
        assert sleeps == [1]
        assert milvus.is_search_ready() is True
    finally:
        milvus.close_store()


def test_milvus_store_uses_builtin_function_as_store_sparse():
    from store import milvus
    from sparse.milvus_bm25 import MilvusBM25Sparse

    assert milvus._sparse_uses_store(MilvusBM25Sparse())


def test_milvus_close_store_closes_native_client(monkeypatch):
    from store import milvus

    client = FakeMilvusClient("http://localhost:19530")
    monkeypatch.setattr(milvus, "_client", client)

    milvus.close_store()

    assert client.closed is True
    assert milvus._client is None


def test_milvus_close_store_releases_local_lite_server(monkeypatch):
    from store import milvus

    released = []

    monkeypatch.setattr(milvus, "_uri", "milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_connection_uri", lambda uri: "/tmp/rag/milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_release_lite_server", lambda uri: released.append(uri))

    milvus.close_store()

    assert released == ["/tmp/rag/milvus_data/lite/lite.db"]


def test_milvus_close_store_does_not_release_standalone_server(monkeypatch):
    from store import milvus

    released = []

    monkeypatch.setattr(milvus, "_uri", "http://localhost:19530")
    monkeypatch.setattr(milvus, "_release_lite_server", lambda uri: released.append(uri))

    milvus.close_store()

    assert released == []


def test_milvus_drop_collections_keeps_local_lite_server_for_following_start(monkeypatch):
    from store import milvus

    released = []

    FakeMilvusClient.instances = []
    monkeypatch.setattr(milvus, "_uri", "milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_connection_uri", lambda uri: "/tmp/rag/milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_release_lite_server", lambda uri: released.append(uri))
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    milvus.drop_collections()

    assert released == []


def test_milvus_search_and_query_use_configured_timeout(monkeypatch):
    from store import milvus

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    monkeypatch.setattr(milvus, "_ready", True)
    monkeypatch.setattr(milvus, "_timeout", 30)
    monkeypatch.setattr(milvus, "_dense", FakeDense())
    monkeypatch.setattr(milvus, "_client", client)
    monkeypatch.setattr(milvus, "QDRANT_CHUNKS_COLLECTION", "chunks")
    monkeypatch.setattr(milvus, "_sparse_uses_store", lambda sparse=None: True)

    milvus.search_dense("query", 5, "file_id in ['file_a']")
    milvus.get_search_documents("file_id in ['file_a']")

    assert client.searches[0][1]["timeout"] == 30
    assert client.queries[0][1]["timeout"] == 30


def test_milvus_store_uses_ip_metric_for_embedding_sparse_and_bm25_metric_for_builtin_sparse(monkeypatch):
    from store import milvus
    from sparse.milvus_bge_m3 import MilvusBGEM3Sparse
    from sparse.milvus_bm25 import MilvusBM25Sparse

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

    milvus.close_store()
    monkeypatch.setattr(milvus, "_sparse", FakeStoreSparse())
    assert milvus._search_params_for_mode("sparse") == {"metric_type": "IP", "params": {}}
    assert milvus._search_params_for_mode("hybrid")[1] == {"metric_type": "IP", "params": {}}

    milvus.close_store()
    monkeypatch.setattr(milvus, "_sparse", MilvusBM25Sparse())
    assert milvus._search_params_for_mode("sparse") == {"metric_type": "BM25", "params": {}}
    assert milvus._search_params_for_mode("hybrid")[1] == {"metric_type": "BM25", "params": {}}


def test_milvus_lite_uses_flat_dense_index_to_avoid_hnsw_faiss_background_build(monkeypatch):
    from store import milvus
    from sparse.milvus_bge_m3 import MilvusBGEM3Sparse
    from sparse.milvus_bm25 import MilvusBM25Sparse

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

    milvus.close_store()
    monkeypatch.setattr(milvus, "_uri", "milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_sparse", None)
    assert milvus._index_params_for_mode("dense") == {"metric_type": "L2", "index_type": "FLAT", "params": {}}

    monkeypatch.setattr(milvus, "_sparse", FakeStoreSparse())
    assert milvus._index_params_for_mode("hybrid") == [
        {"metric_type": "L2", "index_type": "FLAT", "params": {}},
        {"metric_type": "IP", "index_type": "SPARSE_INVERTED_INDEX", "params": {"drop_ratio_build": 0.2}},
    ]

    monkeypatch.setattr(milvus, "_sparse", MilvusBM25Sparse())
    assert milvus._index_params_for_mode("hybrid") == [
        {"metric_type": "L2", "index_type": "FLAT", "params": {}},
        {
            "metric_type": "BM25",
            "index_type": "SPARSE_INVERTED_INDEX",
            "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
        },
    ]


def test_milvus_builtin_bm25_hybrid_declares_dense_and_sparse_vector_fields(monkeypatch):
    from store import milvus
    from sparse.milvus_bm25 import MilvusBM25Sparse

    milvus.close_store()
    monkeypatch.setattr(milvus, "_sparse", MilvusBM25Sparse())

    assert milvus._vector_field_for_mode("hybrid") == ["dense", "sparse"]


def test_milvus_standalone_uses_explicit_native_index_params(monkeypatch):
    from store import milvus

    milvus.close_store()
    monkeypatch.setattr(milvus, "_uri", "http://localhost:19530")

    assert milvus._index_params_for_mode("dense") == {"metric_type": "L2", "index_type": "AUTOINDEX", "params": {}}


def test_milvus_store_creates_collection_without_placeholder_documents(monkeypatch):
    from store import milvus

    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)
    milvus.close_store()
    try:
        milvus.init_store(
            dense=FakeDense(),
            uri="http://localhost:19530",
            chunks_collection="chunks",
        )

        client = FakeMilvusClient.instances[0]
        assert client.collections == {"chunks"}
        assert client.created[0]["collection_name"] == "chunks"
        assert client.inserted == []
    finally:
        milvus.close_store()


def test_milvus_add_file_chunks_inserts_native_rows(monkeypatch):
    from store import milvus

    client = FakeMilvusClient("http://localhost:19530")
    monkeypatch.setattr(milvus, "_ready", True)
    monkeypatch.setattr(milvus, "_client", client)
    monkeypatch.setattr(milvus, "_dense", FakeDense())
    monkeypatch.setattr(milvus, "_sparse", None)
    monkeypatch.setattr(milvus, "QDRANT_CHUNKS_COLLECTION", "chunks")

    count = milvus.add_file_chunks([
        {"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}},
    ], "file1")

    assert count == 1
    assert client.inserted[0][0] == "chunks"
    assert client.inserted[0][1][0]["pk"] == milvus._point_id("chunk-a")
    assert client.inserted[0][1][0]["text"] == "hello"
    assert client.inserted[0][1][0]["file_id"] == "file1"
    assert client.inserted[0][1][0]["vector"] == [0.1, 0.2, 0.3]
