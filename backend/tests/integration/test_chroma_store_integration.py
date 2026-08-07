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
        "metadata": {"filename": filename},
    }


def test_chroma_store_adds_searches_lists_and_deletes_common_documents(tmp_path):
    from store import chroma

    chroma.close_store()
    try:
        chroma.init_store(
            dense=FakeDense(),
            sparse=None,
            persist_dir=str(tmp_path),
            common_collection="chroma_common_it",
            scoped_collection="chroma_scoped_it",
        )

        chroma.add_common_documents(
            [_chunk("alpha-1", "alpha.txt", "alpha knowledge")],
            namespace="tenant_a",
        )

        docs = chroma.list_common_documents(namespace="tenant_a")
        assert docs[0]["filename"] == "alpha.txt"
        assert docs[0]["chunks"] == 1

        results = chroma.search_dense(
            "common",
            "alpha",
            1,
            chroma.build_common_filter("tenant_a"),
        )
        assert results[0]["content"] == "alpha knowledge"

        assert chroma.delete_common_document("alpha.txt", namespace="tenant_a") == 1
        assert chroma.list_common_documents(namespace="tenant_a") == []
    finally:
        chroma.close_store()


def test_chroma_local_store_rejects_store_sparse_with_clear_error(tmp_path):
    from store import chroma

    chroma.close_store()
    try:
        with pytest.raises(RuntimeError, match="Chroma Cloud supports sparse vector indexing"):
            chroma.init_store(
                dense=FakeDense(),
                sparse=FakeChromaSparse(),
                persist_dir=str(tmp_path),
                common_collection="chroma_sparse_common_it",
                scoped_collection="chroma_sparse_scoped_it",
            )
    finally:
        chroma.close_store()
