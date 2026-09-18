from __future__ import annotations

import logging

import shared.device as device

logger = logging.getLogger("services.inference")


class BgeM3Sparse:
    def __init__(self, model_name: str, batch_size: int = 4, release_memory: str = "per_batch"):
        self.model_name = model_name
        self.batch_size = batch_size
        self.release_memory = release_memory
        self._model = None
        self.ready = False

    def start(self) -> None:
        if self._model is None:
            logger.info("Loading sparse model", extra={"event": "model_load", "component": "sparse", "model": self.model_name})
            from FlagEmbedding import BGEM3FlagModel
            self._model = BGEM3FlagModel(self.model_name, use_fp16=device.auto_device() == "cuda", return_dense=False, return_sparse=True, return_colbert_vecs=False)
        self._model.encode(["warmup"], batch_size=1, return_dense=False, return_sparse=True, return_colbert_vecs=False)
        self.ready = True

    def stop(self) -> None:
        self._model = None
        self.ready = False
        device.release_memory()

    def embed_query(self, text: str) -> dict[int, float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        self._require_ready()
        try:
            result = self._model.encode(texts, batch_size=self.batch_size, return_dense=False, return_sparse=True, return_colbert_vecs=False)
            return [_normalize_sparse_vector(vector) for vector in result["lexical_weights"]]
        finally:
            if self.release_memory in {"per_batch", "after_call"}:
                device.release_memory()

    def _require_ready(self) -> None:
        if not self.ready or self._model is None:
            raise RuntimeError("sparse is not initialized")


def _normalize_sparse_vector(vector) -> dict[int, float]:
    return {
        int(index): float(value)
        for index, value in dict(vector).items()
        if float(value) != 0.0
    }
