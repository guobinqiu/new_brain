"""Search plan and execution pipeline."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from contextlib import nullcontext
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from pydantic import ConfigDict
from services.rag.core.search.trace import SearchTrace
from shared.upstream import UpstreamServiceError
from services.rag.clients.vector.base import VectorClient


logger = logging.getLogger(__name__)


class SearchPipeline:
    def __init__(self, vector: VectorClient, rerank: Any = None, vector_backend: str | None = None):
        self.vector_client = vector
        self.rerank_client = rerank
        self.vector_backend = vector_backend
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.ready = False

    def stop(self) -> None:
        self.close()


class _SearchRetriever(BaseRetriever):
    vector_client: Any
    vector_backend: str | None = None
    query: str
    mode: str = "dense"
    rrf_k: int = 60
    app_id: str | None = None
    file_ids: list[str] | None = None
    trace: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(
        self,
        context: dict[str, Any],
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if context["skip"]:
            return []
        if self.trace is None:
            items = self._retrieve_items(context)
        else:
            with self.trace.stage(self.mode, **self._trace_fields()) as stage:
                items = self._retrieve_items(context)
                stage["count"] = len(items)
                stage["hit_count"] = len(items)
        return [_item_to_document(item) for item in items]

    def _trace_fields(self) -> dict[str, str]:
        return {"backend": _vector_backend(self.vector_client, self.vector_backend), "retriever": self.mode}

    def _retrieve_items(self, context: dict[str, Any]) -> list[dict]:
        if self.mode == "sparse":
            return _retrieve_sparse(self.vector_client, context["metadata_filter"], self.query, context["retrieve_limit"], self.trace, self.vector_backend)
        if self.mode == "hybrid":
            return _retrieve_hybrid(
                self.vector_client,
                context["metadata_filter"],
                self.query,
                context["retrieve_limit"],
                self.rrf_k,
                self.trace,
                self.vector_backend,
            )
        return _retrieve_dense(self.vector_client, context["metadata_filter"], self.query, context["retrieve_limit"], self.trace, self.vector_backend)


@dataclass(frozen=True)
class SearchPlan:
    query: str
    app_id: str | None = None
    mode: str = "dense"
    top_k: int = 5
    rerank_fetch_k: int | None = None
    rerank: bool = False
    rrf_k: int = 60
    file_ids: list[str] | None = None

    def __post_init__(self):
        if self.mode not in {"dense", "sparse", "hybrid"}:
            raise ValueError("mode must be dense, sparse, or hybrid")
        if self.rerank and self.rerank_fetch_k is not None and self.rerank_fetch_k < self.top_k:
            raise ValueError("rerank_fetch_k must be >= top_k")
        if self.file_ids is not None:
            if len(self.file_ids) == 0:
                raise ValueError("file_ids cannot be empty")
            if len(self.file_ids) > 1000:
                raise ValueError("file_ids exceeds max limit: 1000")


class _SearchExecutor:
    def __init__(
        self,
        plan: SearchPlan,
        vector: VectorClient,
        rerank: Any = None,
        vector_backend: str | None = None,
        search_trace: bool = False,
    ):
        self.plan = plan
        self.vector_client = vector
        self.rerank_client = rerank
        self.vector_backend = vector_backend
        self._retrieve_limit = self.plan.top_k
        self.trace = SearchTrace(search_trace)
        if self.plan.rerank and self.rerank_client is None:
            raise ValueError("rerank is enabled but inference rerank client is not configured")

    def execute(self) -> list[dict]:
        try:
            results = self._build_runnable().invoke(None, config=self._runnable_config())
        except Exception as exc:
            self.trace.finish(self.plan, result_count=0, status="error", error=str(exc))
            raise
        self.trace.finish(self.plan, result_count=len(results), status="ok")
        return results

    def _runnable_config(self) -> dict:
        return {
            "run_name": "search",
            "tags": [
                "rag-search",
                f"mode:{self.plan.mode}",
                f"rerank:{str(self.plan.rerank).lower()}",
            ],
            "metadata": {
                "query": self.plan.query,
                "app_id": self.plan.app_id,
                "mode": self.plan.mode,
                "top_k": self.plan.top_k,
                "rerank_fetch_k": self.plan.rerank_fetch_k,
                "rerank": self.plan.rerank,
                "rrf_k": self.plan.rrf_k,
                "file_ids": list(self.plan.file_ids or []),
            },
        }

    def _build_runnable(self):
        return (
            RunnableLambda(self._prepare_plan, name="prepare_plan")
            | self._retrieve_runnable()
            | RunnableLambda(self._dedupe_items, name="dedupe")
            | RunnableLambda(self._rerank_items, name="rerank")
            | RunnableLambda(self._format_response, name="format_response")
        )

    def _prepare_plan(self, _):
        with self.trace.stage("prepare_plan"):
            retrieve_limit = self.plan.rerank_fetch_k if self.plan.rerank and self.plan.rerank_fetch_k is not None else self.plan.top_k
            self._retrieve_limit = retrieve_limit
            return {
                "retrieve_limit": retrieve_limit,
                "metadata_filter": self.vector_client.build_file_filter(self.plan.file_ids),
                "skip": False,
            }

    def _retrieve_runnable(self):
        return self._retriever() | RunnableLambda(_documents_to_items, name=f"{self.plan.mode}_items")

    def _retriever(self) -> _SearchRetriever:
        return _SearchRetriever(
            vector_client=self.vector_client,
            query=self.plan.query,
            mode=self.plan.mode,
            rrf_k=self.plan.rrf_k,
            app_id=self.plan.app_id,
            file_ids=self.plan.file_ids,
            trace=self.trace,
            vector_backend=self.vector_backend,
            name=self.plan.mode,
        )

    def _dedupe_items(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("dedupe", backend="app", retriever="dedupe") as stage:
            deduped = _dedupe(items)
            stage["count"] = len(deduped)
            stage["hit_count"] = len(deduped)
            return deduped

    def _rerank_items(self, items: list[dict]) -> list[dict]:
        if not self.plan.rerank:
            return items
        with self.trace.stage("rerank", backend="inference", retriever="rerank") as stage:
            try:
                ranked = self.rerank_client.rerank(self.plan.query, items, self.plan.top_k)
            except Exception as exc:
                stage["error"] = str(exc)
                logger.warning("rerank failed, return retrieved items", exc_info=exc)
                return items
            stage["count"] = len(ranked)
            stage["hit_count"] = len(ranked)
            return ranked

    def _format_response(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("format_response", backend="app", retriever="format") as stage:
            items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            results = [_public_item(item) for item in items[: self.plan.top_k]]
            stage["count"] = len(results)
            stage["hit_count"] = len(results)
            return results


def _retrieve_dense(vector: VectorClient, metadata_filter, query: str, limit: int, trace=None, vector_backend: str | None = None) -> list[dict]:
    if hasattr(vector, "encode_dense_query") and hasattr(vector, "query_dense_vector"):
        with _optional_stage(trace, "dense_encode", backend="model", retriever="dense") as stage:
            query_vector = vector.encode_dense_query(query)
            stage["dimension"] = len(query_vector) if hasattr(query_vector, "__len__") else None
        with _optional_stage(trace, "dense_query", backend=_vector_backend(vector, vector_backend), retriever="dense") as stage:
            items = vector.query_dense_vector(query_vector, limit, metadata_filter)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items
    return vector.search_dense(query, limit, metadata_filter)


def _retrieve_sparse(vector: VectorClient, metadata_filter, query: str, limit: int, trace=None, vector_backend: str | None = None) -> list[dict]:
    if hasattr(vector, "encode_sparse_query") and hasattr(vector, "query_sparse_vector"):
        with _optional_stage(trace, "sparse_encode", backend="model", retriever="sparse") as stage:
            query_vector = vector.encode_sparse_query(query)
            stage["dimension"] = len(query_vector) if hasattr(query_vector, "__len__") else None
        with _optional_stage(trace, "sparse_query", backend=_vector_backend(vector, vector_backend), retriever="sparse") as stage:
            items = vector.query_sparse_vector(query_vector, limit, metadata_filter)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items
    return vector.search_sparse(query, limit, metadata_filter)


def _retrieve_hybrid(
    vector: VectorClient,
    metadata_filter,
    query: str,
    limit: int,
    rrf_k: int,
    trace=None,
    vector_backend: str | None = None,
) -> list[dict]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        dense_future = executor.submit(copy_context().run, _retrieve_dense, vector, metadata_filter, query, limit, trace, vector_backend)
        sparse_future = executor.submit(copy_context().run, _retrieve_sparse, vector, metadata_filter, query, limit, trace, vector_backend)
        dense_items = dense_future.result()
        try:
            sparse_items = sparse_future.result()
        except UpstreamServiceError:
            return dense_items[:limit]
    with _optional_stage(trace, "rrf", backend="app", retriever="rrf", rrf_k=rrf_k) as stage:
        items = _merge_rrf(dense_items, sparse_items, rrf_k)[:limit]
        stage["count"] = len(items)
        stage["hit_count"] = len(items)
        return items


def _merge_rrf(dense_items: list[dict], sparse_items: list[dict], rrf_k: int) -> list[dict]:
    merged: dict[object, dict] = {}
    for items in (dense_items, sparse_items):
        for rank, item in enumerate(items, start=1):
            key = _dedupe_key(item)
            if key not in merged:
                result = dict(item)
                result["_score"] = 0.0
                merged[key] = result
            merged[key]["_score"] = float(merged[key].get("_score", 0.0)) + 1.0 / (rrf_k + rank)
    results = list(merged.values())
    results.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
    return results


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        key = _dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dedupe_key(item: dict):
    return item.get("id") or (item.get("content"), tuple(sorted((item.get("metadata") or {}).items())))


def _public_item(item: dict) -> dict:
    result = {key: value for key, value in item.items() if not key.startswith("_")}
    if "_score" in item:
        result["score"] = float(item["_score"])
    return result


def _item_to_document(item: dict) -> Document:
    metadata = dict(item.get("metadata") or {})
    metadata["_rag_item"] = item
    return Document(
        page_content=item.get("content", ""),
        metadata=metadata,
        id=item.get("id") or None,
    )


def _documents_to_items(documents: list[Document]) -> list[dict]:
    return [dict(document.metadata["_rag_item"]) for document in documents]


def _optional_stage(trace, name: str, **fields):
    if trace is None:
        return nullcontext(fields)
    return trace.stage(name, **fields)


def _vector_backend(vector: VectorClient, configured: str | None = None) -> str:
    if configured:
        return configured
    backend_name = getattr(vector, "backend_name", None)
    if backend_name:
        return str(backend_name)
    name = vector.__class__.__name__.lower()
    if "qdrant" in name or name == "fakevector":
        return "qdrant"
    if "milvus" in name:
        return "milvus"
    return name.removesuffix("vector") or "unknown"
