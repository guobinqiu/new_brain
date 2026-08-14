from __future__ import annotations

from sparse.bge_m3_common import BGEM3LexicalEncoder


class MilvusBGEM3Sparse:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._encoder = BGEM3LexicalEncoder(model_name)

    def start(self) -> None:
        self._encoder.start()

    def stop(self) -> None:
        self._encoder.stop()

    @property
    def ready(self) -> bool:
        return self._encoder.ready

    def embed_query(self, query: str) -> dict[int, float]:
        return self._encoder.embed_query(query)

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        return self._encoder.embed_documents(texts)

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        raise RuntimeError("BGE-M3 sparse uses store search")
