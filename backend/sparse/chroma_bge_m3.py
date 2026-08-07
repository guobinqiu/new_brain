from __future__ import annotations

from typing import Any

from chromadb import SparseVector
from chromadb.utils.embedding_functions import SparseEmbeddingFunction

from sparse.bge_m3_common import BGEM3LexicalEncoder


class ChromaBGEM3Sparse(SparseEmbeddingFunction[list[str]]):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._encoder = BGEM3LexicalEncoder(model_name)

    @staticmethod
    def name() -> str:
        return "bge_m3"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "ChromaBGEM3Sparse":
        return ChromaBGEM3Sparse(config["model_name"])

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    def start(self) -> None:
        self._encoder.start()

    def stop(self) -> None:
        self._encoder.stop()

    @property
    def ready(self) -> bool:
        return self._encoder.ready

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        raise RuntimeError("BGE-M3 sparse uses store search")

    def __call__(self, input: list[str]) -> list[SparseVector]:
        return [_to_sparse_vector(weights) for weights in self._encoder.embed_documents(input)]


def _to_sparse_vector(weights: dict) -> SparseVector:
    items = sorted((int(index), float(value)) for index, value in weights.items() if float(value) != 0.0)
    return SparseVector(
        indices=[index for index, _ in items],
        values=[value for _, value in items],
    )
