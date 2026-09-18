from __future__ import annotations

import logging

import shared.device as device

logger = logging.getLogger("services.inference")


class HuggingFaceDense:
    def __init__(self, model_name: str, batch_size: int = 4, release_memory: str = "per_batch"):
        self.model_name = model_name
        self.batch_size = batch_size
        self.release_memory = release_memory
        self._dense = None
        self._vector_size: int | None = None
        self.ready = False

    def start(self) -> None:
        if self._dense is None:
            logger.info("Loading dense model", extra={"event": "model_load", "component": "dense", "model": self.model_name})
            from langchain_huggingface import HuggingFaceEmbeddings
            self._dense = HuggingFaceEmbeddings(model_name=self.model_name, model_kwargs={"device": device.auto_device()})
        if self._vector_size is None:
            self._vector_size = len(self._dense.embed_query("dimension probe"))
            self._dense.embed_documents(["warmup"])
        self.ready = True

    def stop(self) -> None:
        self._dense = None
        self._vector_size = None
        self.ready = False
        device.release_memory()

    def embed_query(self, text: str) -> list[float]:
        self._require_ready()
        return self._dense.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._require_ready()
        vectors = []
        try:
            for index in range(0, len(texts), self.batch_size):
                try:
                    vectors.extend(self._dense.embed_documents(texts[index:index + self.batch_size]))
                finally:
                    if self.release_memory == "per_batch":
                        device.release_memory()
        finally:
            if self.release_memory == "after_call":
                device.release_memory()
        return vectors

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
