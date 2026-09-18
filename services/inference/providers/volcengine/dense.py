from __future__ import annotations

import httpx

from shared.retry import retry_call

from .base import _VolcengineModel
from .retryable import _embedding_retryable
from .schemas import _EmbeddingResponse


class VolcengineDenseClient(_VolcengineModel):
    path = "/embeddings/multimodal"
    operation = "embedding"
    _retryable = staticmethod(_embedding_retryable)

    @property
    def vector_size(self) -> int:
        return self.config.dimensions

    def _authorize(self, request: httpx.Request) -> None:
        request.headers["Authorization"] = f"Bearer {self.config.api_key}"

    def embed_query(self, text: str) -> list[float]:
        return self._create_dense_embeddings(text)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._create_dense_embeddings(texts)

    def _create_dense_embeddings(self, value: str | list[str]) -> list[list[float]]:
        return retry_call(
            lambda: self._create_dense_embeddings_once(value),
            self.config.retry,
            operation_name="inference.volcengine.dense",
        )

    def _create_dense_embeddings_once(self, value: str | list[str]) -> list[list[float]]:
        texts = [value] if isinstance(value, str) else value
        vectors = []
        # 多模态 input 中的内容融合为一个向量，每段文本需要独立请求
        for text in texts:
            with self._call({
                "model": self.model, "input": [{"type": "text", "text": text}],
                "dimensions": self.config.dimensions, "encoding_format": "float",
            }) as body:
                vector = _EmbeddingResponse.model_validate(body, strict=True).data.embedding
                if len(vector) != self.config.dimensions:
                    raise ValueError("Invalid embedding dimensions")
                vectors.append(vector)
        return vectors
