from __future__ import annotations

import logging

import device

from config import RERANKER_MODEL_DIR

logger = logging.getLogger("rag.app")

MODEL_NAME = RERANKER_MODEL_DIR
RERANK_MIN_SCORE = 0.0


class CrossEncoderRerank:
    def __init__(self, model_name: str = MODEL_NAME, batch_size: int = 4):
        self.model_name = model_name
        self.batch_size = batch_size
        self._reranker = None
        self.ready = False

    def start(self) -> None:
        if self._reranker is None:
            self._reranker = self._load_reranker()
        self.ready = True

    def stop(self) -> None:
        self._reranker = None
        self.ready = False
        device.release_memory()

    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        if not items:
            return []
        if not self.ready or self._reranker is None:
            raise RuntimeError("rerank is not initialized")

        pairs = [(query, item["content"]) for item in items]
        try:
            if hasattr(self._reranker, "predict"):
                scores = self._reranker.predict(pairs, batch_size=self.batch_size)
            else:
                scores = self._reranker.score(pairs)
        finally:
            device.release_memory()

        scored = [(item, float(score)) for item, score in zip(items, scores) if float(score) >= RERANK_MIN_SCORE]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item, _score in scored[:top_k]
        ]

    def _load_reranker(self):
        logger.info("Loading reranker model", extra={"event": "model_load", "component": "rerank", "model": self.model_name})
        from sentence_transformers import CrossEncoder
        return CrossEncoder(model_name=self.model_name, device=device.auto_device())
