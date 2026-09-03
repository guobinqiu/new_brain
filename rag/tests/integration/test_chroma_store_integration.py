import pytest
from chromadb.utils.embedding_functions import SparseEmbeddingFunction


pytestmark = pytest.mark.integration


class FakeDense:
    ready = False

    def __init__(self):
        self._embeddings = FakeEmbeddings()

    def start(self):
        self.ready = True

    def stop(self):
        self.ready = False

    def embed_query(self, text):
        return self._embeddings.embed_query(text)

    def embed_documents(self, texts):
        return self._embeddings.embed_documents(texts)

    def as_langchain_dense(self):
        return self._embeddings


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        lowered = text.lower()
        return [
            1.0 if "alpha" in lowered else 0.0,
            1.0 if "beta" in lowered else 0.0,
            1.0 if "gamma" in lowered else 0.0,
        ]


class FakeChromaSparse(SparseEmbeddingFunction[list[str]]):
    ready = False

    def __init__(self):
        pass

    @staticmethod
    def name():
        return "fake_sparse"

    @staticmethod
    def build_from_config(config):
        return FakeChromaSparse()

    def get_config(self):
        return {}

    def start(self):
        self.ready = True

    def stop(self):
        self.ready = False

    def search(self, query, documents, limit):
        raise RuntimeError("Chroma sparse should use collection search")

    def __call__(self, input):
        from chromadb import SparseVector

        vectors = []
        for text in input:
            lowered = text.lower()
            pairs = []
            if "alpha" in lowered:
                pairs.append((1, 1.0))
            if "beta" in lowered:
                pairs.append((2, 1.0))
            if "gamma" in lowered:
                pairs.append((3, 1.0))
            vectors.append(SparseVector(indices=[index for index, _ in pairs], values=[value for _, value in pairs]))
        return vectors


def _chunk(chunk_id, filename, content):
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {"filename": filename, "chunk_index": 0},
    }


def test_chroma_store_adds_searches_and_deletes_file_chunks(tmp_path):
    from rag.scope import app_collection
    from rag.store.chroma import ChromaStore

    dense = FakeDense()
    dense.start()
    store = ChromaStore(
        dense=dense,
        sparse=None,
        persist_dir=str(tmp_path),
    )
    store.start()

    try:
        store.ensure_app_collection("chromait")
        with app_collection("chromait"):
            store.add_file_chunks(
                [_chunk("alpha-1", "alpha.txt", "alpha knowledge")],
                file_id="chromafilealpha",
            )

            docs = store.get_search_documents(store.build_file_filter(["chromafilealpha"]))
            assert docs[0]["metadata"]["filename"] == "alpha.txt"

            results = store.search_dense(
                "alpha",
                1,
                store.build_file_filter(["chromafilealpha"]),
            )
            assert results[0]["content"] == "alpha knowledge"

            assert store.delete_file_chunks("chromafilealpha") == 1
            assert store.get_search_documents(store.build_file_filter(["chromafilealpha"])) == []
    finally:
        store.stop()


def test_chroma_local_store_rejects_store_sparse_with_clear_error(tmp_path):
    from rag.store.chroma import ChromaStore

    dense = FakeDense()
    dense.start()
    sparse = FakeChromaSparse()
    sparse.start()
    store = ChromaStore(
        dense=dense,
        sparse=sparse,
        persist_dir=str(tmp_path),
    )
    store.start()

    with pytest.raises(RuntimeError, match="本地 Chroma 不支持 vector sparse"):
        store.ensure_app_collection("chromasparseit")
