from __future__ import annotations

import httpx

from services.inference.app.config import VllmConfig

from .dense import VllmDenseClient
from .rerank import VllmRerankClient


class VllmInferenceClient:
    def __init__(self, config: VllmConfig, *, http_client: httpx.Client | None = None):
        self.dense = VllmDenseClient(
            config.dense_url,
            config.dense_model,
            config.dense_timeout,
            http_client,
            dimensions=config.dimensions,
            retry=config.retry,
        )
        self.sparse = None
        self.rerank = VllmRerankClient(
            config.rerank_url,
            config.rerank_model,
            config.rerank_timeout if config.rerank_timeout is not None else config.dense_timeout,
            http_client,
            config.retry,
        ) if config.rerank_url and config.rerank_model else None

    def ping(self) -> bool:
        return self.dense.ready and (self.rerank is None or self.rerank.ready)

    def close(self) -> None:
        self.dense.close()
        if self.rerank is not None:
            self.rerank.close()
