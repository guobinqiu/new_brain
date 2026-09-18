from __future__ import annotations

import httpx


def _embedding_retryable(response: httpx.Response) -> bool:
    return 500 <= response.status_code < 600


def _rerank_retryable(response: httpx.Response) -> bool:
    return 500 <= response.status_code < 600
