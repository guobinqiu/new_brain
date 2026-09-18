from __future__ import annotations

import httpx
from volcengine.auth.SignerV4 import SignerV4
from volcengine.Credentials import Credentials
from volcengine.base.Request import Request

from shared.upstream import UpstreamServiceError
from shared.retry import retry_call

from .base import _VolcengineModel
from .retryable import _rerank_retryable
from .schemas import _RerankResponse


class VikingRerankClient(_VolcengineModel):
    path = "/api/knowledge/service/rerank"
    operation = "rerank"
    _retryable = staticmethod(_rerank_retryable)

    def _authorize(self, request: httpx.Request) -> None:
        signed = Request()
        signed.method = request.method
        signed.path = request.url.path
        signed.body = request.content.decode("utf-8")
        signed.headers = {"Content-Type": "application/json", "Host": request.headers["host"]}
        SignerV4.sign(signed, Credentials(self.config.access_key, self.config.secret_key, "air", self.config.region))
        request.headers.update(signed.headers)

    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        return retry_call(
            lambda: self._rerank_once(query, items, top_k),
            self.config.retry,
            operation_name="inference.volcengine.rerank",
        )

    def _rerank_once(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        with self._call({
            "rerank_model": self.model,
            "datas": [{"query": query, "content": item["content"]} for item in items],
        }) as body:
            result = _RerankResponse.model_validate(body, strict=True)
            if result.code != 0:
                raise UpstreamServiceError(service="inference", error=result.message, retryable=False, status_code=502)
            if result.data is None or len(result.data.scores) != len(items):
                raise ValueError("Invalid rerank score count")
            ranked = sorted(zip(items, result.data.scores), key=lambda pair: pair[1], reverse=True)
            return [dict(item, _score=score) for item, score in ranked[:top_k]]
