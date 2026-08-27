from __future__ import annotations

import logging

import device

logger = logging.getLogger("rag.app")


class BGEM3LexicalEncoder:
    def __init__(self, model_name: str, batch_size: int = 4):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None
        self.ready = False

    def start(self) -> None:
        if self._model is None:
            logger.info("Loading BGE-M3 sparse model", extra={"event": "model_load", "component": "sparse", "model": self.model_name})
            self._model = self._load_model()
        self.ready = True

    def stop(self) -> None:
        self._model = None
        self.ready = False
        device.release_memory()

    def embed_query(self, text: str) -> dict[int, float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        self._require_ready()
        vectors = []
        for index in range(0, len(texts), self.batch_size):
            try:
                output = self._model.encode(
                    texts[index:index + self.batch_size],
                    return_dense=False,
                    return_sparse=True,
                    return_colbert_vecs=False,
                )
                vectors.extend(_normalize_lexical_weights(weights) for weights in output["lexical_weights"])
            finally:
                device.release_memory()
        return vectors

    def _load_model(self):
        from FlagEmbedding import BGEM3FlagModel

        return BGEM3FlagModel(self.model_name, use_fp16=device.auto_device() == "cuda")

    def _require_ready(self) -> None:
        if not self.ready or self._model is None:
            raise RuntimeError("BGE-M3 sparse is not initialized")


def _normalize_lexical_weights(weights: dict) -> dict[int, float]:
    return {
        int(index): float(value)
        for index, value in weights.items()
        if float(value) != 0.0
    }
