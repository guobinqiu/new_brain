from __future__ import annotations

from typing import Any

import httpx

from shared.service_auth import service_auth_headers
from shared.tracing import trace_headers
from shared.deadline import request_timeout
from shared.upstream import UpstreamServiceError, internal_error
from services.rag.clients.inference.base import InferenceClient


class HttpInferenceClient(InferenceClient):
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 120.0,
        embedding_timeout: float | None = None,
        rerank_timeout: float | None = None,
        api_key: str | None = None,
    ):
        self.embedding_timeout = embedding_timeout if embedding_timeout is not None else timeout
        self.rerank_timeout = rerank_timeout if rerank_timeout is not None else timeout
        self.dense = HttpDenseClient(base_url, timeout=self.embedding_timeout, api_key=api_key)
        self.sparse = None
        self.rerank = None
        self.ready = False

    def start(self) -> None:
        try:
            response = self.dense._client.get(
                f"{self.dense.base_url}/ready",
                headers={**service_auth_headers(self.dense.api_key), **trace_headers()},
                timeout=min(self.embedding_timeout, 10.0),
            )
            response.raise_for_status()
            capabilities = response.json()["capabilities"]
            if capabilities["sparse"]:
                self.sparse = HttpSparseClient(self.dense.base_url, timeout=self.embedding_timeout, api_key=self.dense.api_key)
            if capabilities["rerank"]:
                self.rerank = HttpRerankClient(self.dense.base_url, timeout=self.rerank_timeout, api_key=self.dense.api_key)
            self.ready = True
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise internal_error("inference", exc) from exc

    def close(self) -> None:
        for client in (self.rerank, self.sparse, self.dense):
            if client is not None:
                client.close()
        self.ready = False

    def stop(self) -> None:
        self.close()

    def ping(self) -> bool:
        return self.dense.ping()


class HttpDenseClient:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 60.0, api_key: str | None = None, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self._vector_size: int | None = None
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.ready = False
        self._client.close()

    def stop(self) -> None:
        self.close()

    def ping(self) -> bool:
        try:
            response = self._client.get(
                f"{self.base_url}/ready",
                headers={**service_auth_headers(self.api_key), **trace_headers()},
                timeout=min(self.timeout, 1.0),
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def embed_query(self, text: str) -> list[float]:
        return self._create_dense_embeddings(text)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._create_dense_embeddings(texts)

    def _create_dense_embeddings(self, value: str | list[str]) -> list[list[float]]:
        try:
            response = self._client.post(
                f"{self.base_url}/v1/embeddings",
                json={"input": value, "model": self.model},
                headers={**service_auth_headers(self.api_key), **trace_headers()},
                timeout=request_timeout(self.timeout),
            )
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda item: item["index"])
            return [row["embedding"] for row in rows]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise internal_error("inference", exc) from exc

    def as_langchain_dense(self) -> Any:
        raise RuntimeError("remote dense client does not expose a LangChain embedding object")

    @property
    def vector_size(self) -> int:
        if self._vector_size is None:
            try:
                response = self._client.get(
                    f"{self.base_url}/v1/models",
                    headers={**service_auth_headers(self.api_key), **trace_headers()},
                    timeout=request_timeout(self.timeout),
                )
                response.raise_for_status()
                self._vector_size = int(response.json()["dense"]["dimensions"])
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise internal_error("inference", exc) from exc
        return self._vector_size


class HttpSparseClient:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 60.0, api_key: str | None = None, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.ready = False
        self._client.close()

    def stop(self) -> None:
        self.close()

    def embed_query(self, text: str) -> dict[int, float]:
        return self._create_sparse_embeddings(text)[0]

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        return self._create_sparse_embeddings(texts)

    def _create_sparse_embeddings(self, value: str | list[str]) -> list[dict[int, float]]:
        try:
            response = self._client.post(
                f"{self.base_url}/v1/sparse_embeddings",
                json={"input": value, "model": self.model},
                headers={**service_auth_headers(self.api_key), **trace_headers()},
                timeout=request_timeout(self.timeout),
            )
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda item: item["index"])
            return [
                {int(index): float(value) for index, value in zip(row["indices"], row["values"])}
                for row in rows
            ]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise internal_error("inference", exc) from exc


class HttpRerankClient:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 60.0, api_key: str | None = None, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.ready = False
        self._client.close()

    def stop(self) -> None:
        self.close()

    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        try:
            response = self._client.post(
                f"{self.base_url}/v1/rerank",
                json={"query": query, "documents": [item["content"] for item in items], "top_k": top_k, "model": self.model},
                headers={**service_auth_headers(self.api_key), **trace_headers()},
                timeout=request_timeout(self.timeout),
            )
            response.raise_for_status()
            results = []
            for row in response.json()["results"]:
                result = dict(items[int(row["index"])])
                result["_score"] = float(row["relevance_score"])
                results.append(result)
            return results
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise UpstreamServiceError(
                    service="inference",
                    error="rerank is not enabled in inference service",
                    retryable=False,
                    status_code=400,
                ) from exc
            raise internal_error("inference", exc) from exc
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise internal_error("inference", exc) from exc
