from __future__ import annotations

import httpx

from shared.retry import retry_call

from .base import _VolcengineModel
from .retryable import _embedding_retryable
from .schemas import _SparseResponse


class VolcengineSparseClient(_VolcengineModel):
    path = "/embeddings/multimodal"
    operation = "sparse_embedding"
    _retryable = staticmethod(_embedding_retryable)

    def _authorize(self, request: httpx.Request) -> None:
        request.headers["Authorization"] = f"Bearer {self.config.api_key}"

    def embed_query(self, text: str) -> dict[int, float]:
        return self._create_sparse_embeddings(text)[0]

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        return self._create_sparse_embeddings(texts)

    def _create_sparse_embeddings(self, value: str | list[str]) -> list[dict[int, float]]:
        return retry_call(
            lambda: self._create_sparse_embeddings_once(value),
            self.config.retry,
            operation_name="inference.volcengine.sparse",
        )

    def _create_sparse_embeddings_once(self, value: str | list[str]) -> list[dict[int, float]]:
        texts = [value] if isinstance(value, str) else value
        vectors = []
        for text in texts:
            with self._call({
                "model": self.model, "input": [{"type": "text", "text": text}],
                "sparse_embedding": {"type": "enabled"}, "encoding_format": "float",
            }) as body:
                entries = _SparseResponse.model_validate(body, strict=True).data.sparse_embedding
                vectors.append({entry.index: entry.value for entry in entries})
        return vectors
