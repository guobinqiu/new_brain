from __future__ import annotations

import httpx

from services.inference.app.config import VolcengineConfig

from .dense import VolcengineDenseClient
from .rerank import VikingRerankClient
from .sparse import VolcengineSparseClient


class VolcengineInferenceClient:
    def __init__(self, config: VolcengineConfig, *, http_client: httpx.Client | None = None):
        self.dense = VolcengineDenseClient(config, config.dense_model, config.base_url, config.dense_timeout, http_client)
        self.sparse = VolcengineSparseClient(
            config, config.sparse_model, config.base_url, config.sparse_timeout if config.sparse_timeout is not None else config.dense_timeout, http_client,
        ) if config.sparse_model else None
        self.rerank = VikingRerankClient(
            config, config.rerank_model, config.rerank_base_url, config.rerank_timeout if config.rerank_timeout is not None else config.dense_timeout, http_client,
        ) if config.rerank_model else None

    def ping(self) -> bool:
        return self.dense.ready and (self.sparse is None or self.sparse.ready) and (self.rerank is None or self.rerank.ready)

    def close(self) -> None:
        self.dense.close()
        if self.sparse is not None:
            self.sparse.close()
        if self.rerank is not None:
            self.rerank.close()
