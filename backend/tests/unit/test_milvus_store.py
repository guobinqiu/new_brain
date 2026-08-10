import pytest


pytestmark = pytest.mark.unit


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


def test_milvus_store_initializes_sparse_and_hybrid_stores_for_store_sparse(monkeypatch):
    from store import milvus
    from langchain_milvus.utils.sparse import BaseSparseEmbedding

    class FakeDense:
        ready = True

        def start(self):
            pass

        def as_langchain_dense(self):
            return self

    class FakeStoreSparse(BaseSparseEmbedding):
        ready = True

        def start(self):
            pass

        def embed_query(self, query):
            return {1: 1.0}

        def embed_documents(self, texts):
            return [{1: 1.0} for _ in texts]

    created = []

    class FakeClient:
        def has_collection(self, collection_name):
            return True

    class FakeMilvus:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.collection_name = kwargs["collection_name"]
            self.client = FakeClient()

    monkeypatch.setattr(milvus, "_load_milvus_class", lambda: FakeMilvus)
    monkeypatch.setattr(milvus, "_dense", None)
    milvus.close_store()
    try:
        milvus.init_store(
            dense=FakeDense(),
            sparse=FakeStoreSparse(),
            uri="http://localhost:19530",
            common_collection="common",
            scoped_collection="scoped",
        )

        assert milvus._sparse_uses_store()
        assert milvus._common_store("sparse")
        assert milvus._common_store("hybrid")
        assert len(created) == 6
    finally:
        milvus.close_store()


def test_milvus_store_passes_timeout_to_connection_args(monkeypatch):
    from store import milvus

    class FakeDense:
        ready = True

        def start(self):
            pass

        def as_langchain_dense(self):
            return self

    created = []

    class FakeClient:
        def has_collection(self, collection_name):
            return True

    class FakeMilvus:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.collection_name = kwargs["collection_name"]
            self.client = FakeClient()

    monkeypatch.setattr(milvus, "_load_milvus_class", lambda: FakeMilvus)
    milvus.close_store()
    try:
        milvus.init_store(
            dense=FakeDense(),
            sparse=None,
            uri="http://localhost:19530",
            timeout=30,
            common_collection="common",
            scoped_collection="scoped",
        )
    finally:
        milvus.close_store()

    assert created[0]["connection_args"]["timeout"] == 30


def test_milvus_store_uses_builtin_function_as_store_sparse():
    from store import milvus
    from sparse.milvus_bm25 import MilvusBM25Sparse

    assert milvus._sparse_uses_store(MilvusBM25Sparse())


def test_milvus_close_store_closes_underlying_clients(monkeypatch):
    from store import milvus

    closed = []

    class FakeClient:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    class FakeStore:
        def __init__(self, name):
            self.client = FakeClient(f"{name}.client")
            self._milvus_client = FakeClient(f"{name}._milvus_client")

    milvus.close_store()
    monkeypatch.setattr(milvus, "_stores", {
        ("common", "dense"): FakeStore("common.dense"),
        ("common", "sparse"): FakeStore("common.sparse"),
    })

    milvus.close_store()

    assert closed == [
        "common.dense.client",
        "common.dense._milvus_client",
        "common.sparse.client",
        "common.sparse._milvus_client",
    ]
    assert milvus._stores == {}


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

    class FakeClient:
        def __init__(self, uri, timeout=None):
            self.uri = uri
            self.timeout = timeout

        def has_collection(self, collection_name):
            return False

        def close(self):
            pass

    monkeypatch.setattr(milvus, "_uri", "milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_connection_uri", lambda uri: "/tmp/rag/milvus_data/lite/lite.db")
    monkeypatch.setattr(milvus, "_release_lite_server", lambda uri: released.append(uri))
    monkeypatch.setattr("pymilvus.MilvusClient", FakeClient)

    milvus.drop_collections()

    assert released == []


def test_milvus_search_and_query_use_configured_timeout(monkeypatch):
    from store import milvus

    calls = []

    class FakeDense:
        def embed_query(self, query):
            return [0.1, 0.2, 0.3]

    class FakeClient:
        def search(self, *args, **kwargs):
            calls.append(("search", kwargs["timeout"]))
            return [[]]

    class FakeMilvusClient:
        def query(self, *args, **kwargs):
            calls.append(("query", kwargs["timeout"]))
            return []

    class FakeStore:
        collection_name = "common"
        client = FakeClient()
        _milvus_client = FakeMilvusClient()

    monkeypatch.setattr(milvus, "_ready", True)
    monkeypatch.setattr(milvus, "_timeout", 30)
    monkeypatch.setattr(milvus, "_dense", FakeDense())
    monkeypatch.setattr(milvus, "_stores", {("common", "dense"): FakeStore()})
    monkeypatch.setattr(milvus, "_sparse_uses_store", lambda sparse=None: True)

    milvus.search_dense("common", "query", 5, "namespace == 'benchmark'")
    milvus.get_search_documents("common", "namespace == 'benchmark'")

    assert calls == [("search", 30), ("query", 30)]


def test_milvus_store_uses_ip_metric_for_embedding_sparse_and_bm25_metric_for_builtin_sparse(monkeypatch):
    from store import milvus
    from langchain_milvus.utils.sparse import BaseSparseEmbedding
    from sparse.milvus_bm25 import MilvusBM25Sparse

    class FakeStoreSparse(BaseSparseEmbedding):
        ready = True

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
    from langchain_milvus.utils.sparse import BaseSparseEmbedding
    from sparse.milvus_bm25 import MilvusBM25Sparse

    class FakeStoreSparse(BaseSparseEmbedding):
        ready = True

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
        {"metric_type": "BM25", "index_type": "AUTOINDEX", "params": {}},
    ]


def test_milvus_builtin_bm25_hybrid_declares_dense_and_sparse_vector_fields(monkeypatch):
    from store import milvus
    from sparse.milvus_bm25 import MilvusBM25Sparse

    milvus.close_store()
    monkeypatch.setattr(milvus, "_sparse", MilvusBM25Sparse())

    assert milvus._vector_field_for_mode("hybrid") == ["dense", "sparse"]


def test_milvus_standalone_keeps_langchain_default_index_params(monkeypatch):
    from store import milvus

    milvus.close_store()
    monkeypatch.setattr(milvus, "_uri", "http://localhost:19530")

    assert milvus._index_params_for_mode("dense") is None


def test_milvus_store_creates_empty_collections_during_initialization(monkeypatch):
    from store import milvus

    class FakeDense:
        ready = True

        def start(self):
            pass

        def as_langchain_dense(self):
            return self

        def embed_query(self, query):
            return [0.1, 0.2, 0.3]

    class FakeClient:
        def __init__(self):
            self.collections = set()

        def has_collection(self, collection_name):
            return collection_name in self.collections

    class FakeMilvus:
        client = FakeClient()
        created = []

        def __init__(self, **kwargs):
            self.collection_name = kwargs["collection_name"]
            self.client = FakeMilvus.client
            self._milvus_client = self.client

        def _create_collection(self, embeddings, metadatas):
            FakeMilvus.created.append((self.collection_name, embeddings, metadatas))
            self.client.collections.add(self.collection_name)

        def _extract_fields(self):
            pass

        def _create_index(self):
            pass

        def _create_search_params(self):
            pass

        def _load(self):
            pass

        def add_documents(self, documents, ids):
            raise AssertionError("placeholder documents should not be inserted to initialize collections")

    monkeypatch.setattr(milvus, "_load_milvus_class", lambda: FakeMilvus)
    milvus.close_store()
    monkeypatch.setattr(milvus, "_dense", None)
    try:
        milvus.init_store(
            dense=FakeDense(),
            uri="http://localhost:19530",
            common_collection="common",
            scoped_collection="scoped",
        )

        assert FakeMilvus.client.collections == {"common", "scoped"}
        assert [item[0] for item in FakeMilvus.created] == ["common", "scoped"]
        assert FakeMilvus.created[0][1] == [[[0.1, 0.2, 0.3]]]
        assert FakeMilvus.created[0][2][0]["namespace"] == "__schema__"
    finally:
        milvus.close_store()
