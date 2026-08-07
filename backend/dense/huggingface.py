from __future__ import annotations

import device

from config import DENSE_MODEL_DIR


class HuggingFaceDense:
    def __init__(self, model_name: str = DENSE_MODEL_DIR):
        self.model_name = model_name
        self._dense = None
        self._vector_size: int | None = None
        self.ready = False

    def start(self) -> None:
        if self._dense is None:
            print(f"Loading dense model: {self.model_name} ...")
            from langchain_huggingface import HuggingFaceEmbeddings
            self._dense = HuggingFaceEmbeddings(model_name=self.model_name, model_kwargs={"device": device.auto_device()})
        if self._vector_size is None:
            self._vector_size = len(self._dense.embed_query("dimension probe"))
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def embed_query(self, text: str) -> list[float]:
        self._require_ready()
        return self._dense.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._require_ready()
        return self._dense.embed_documents(texts)

    def as_langchain_dense(self):
        self._require_ready()
        return self._dense

    @property
    def vector_size(self) -> int:
        self._require_ready()
        return self._vector_size

    def _require_ready(self) -> None:
        if not self.ready or self._dense is None or self._vector_size is None:
            raise RuntimeError("dense is not initialized")
