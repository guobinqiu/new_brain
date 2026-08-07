import pytest


pytestmark = pytest.mark.unit


def test_milvus_store_resolves_local_lite_uri_from_project_root(tmp_path):
    from store import milvus

    project_root = tmp_path / "rag"
    backend_dir = project_root / "backend"
    backend_dir.mkdir(parents=True)

    uri = milvus._connection_uri("milvus_data/lite/native/lite.db", project_root=project_root)

    assert uri == str(project_root / "milvus_data" / "lite" / "native" / "lite.db")
    assert (project_root / "milvus_data" / "lite" / "native").is_dir()


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


def test_milvus_store_uses_builtin_function_as_store_sparse():
    from store import milvus
    from sparse.milvus_bm25 import MilvusBM25Sparse

    assert milvus._sparse_uses_store(MilvusBM25Sparse())


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
