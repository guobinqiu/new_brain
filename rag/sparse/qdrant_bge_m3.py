from __future__ import annotations

from qdrant_client.http.models import SparseVector

from rag.sparse.bge_m3_common import BGEM3LexicalEncoder


class QdrantBGEM3Sparse:
    def __init__(self, model_name: str, batch_size: int = 4, release_memory: str = "per_batch"):
        self.model_name = model_name
        self._encoder = BGEM3LexicalEncoder(model_name, batch_size=batch_size, release_memory=release_memory)

    def start(self) -> None:
        self._encoder.start()

    def stop(self) -> None:
        self._encoder.stop()

    @property
    def ready(self) -> bool:
        return self._encoder.ready

    def supports_search_index(self) -> bool:
        return False

    def supports_sparse_vector(self) -> bool:
        return True

    def embed_query(self, text: str) -> SparseVector:
        return self._embed_one(text)

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [_to_sparse_vector(weights) for weights in self._encoder.embed_documents(texts)]

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        raise RuntimeError("BGE-M3 sparse uses store search")

    def _embed_one(self, text: str) -> SparseVector:
        return self.embed_documents([text])[0]


def _to_sparse_vector(weights: dict) -> SparseVector:
    items = sorted((int(index), float(value)) for index, value in weights.items() if float(value) != 0.0)
    return SparseVector(
        indices=[index for index, _ in items],
        values=[value for _, value in items],
    )
