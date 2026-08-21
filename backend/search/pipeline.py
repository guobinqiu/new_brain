"""Search plan and execution pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda, RunnableParallel
from pydantic import ConfigDict
from rerank.base import Rerank
from search.runner import SearchRunner
from search.trace import SearchTrace
from sparse.base import Sparse
from sparse.bm25 import BM25Sparse
from store.base import Store


class SearchPipeline:
    def __init__(self, store: Store, sparse: Sparse):
        self.store = store
        self.sparse = sparse
        self.ready = False

    def start(self) -> None:
        set_default_store(self.store)
        if not self.sparse.ready:
            raise RuntimeError("sparse is not initialized")
        self.ready = True

    def stop(self) -> None:
        self.ready = False


def init_search():
    BM25Sparse().start()


def init_search_pipeline():
    init_search()


def _clamp_fetch_k(store: Store, fetch_k: int, file_ids: list[str] | None) -> int:
    """把候选池宽度限制到 [1, 当前查询范围总 chunk 数]。"""
    total = store.get_total_chunks(file_ids=file_ids)
    if total <= 0:
        return 1
    return max(1, min(fetch_k, total))


class _SearchRetriever(BaseRetriever):
    store: Any
    sparse: Any = None
    mode: str
    query: str
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
        stage_name = self.mode
        if self.trace is None:
            items = self._retrieve_items(context)
        else:
            with self.trace.stage(stage_name) as stage:
                items = self._retrieve_items(context)
                stage["count"] = len(items)
        return [_item_to_document(item) for item in items]

    def _retrieve_items(self, context: dict[str, Any]) -> list[dict]:
        if self.mode == "dense":
            return _retrieve_dense(self.store, context["metadata_filter"], self.query, context["retrieve_limit"])
        if self.mode == "sparse":
            return _retrieve_sparse(self.store, context["metadata_filter"], self.query, context["retrieve_limit"], self.sparse)
        if self.mode == "hybrid":
            return _retrieve_store_hybrid(self.store, context["metadata_filter"], self.query, context["retrieve_limit"])
        raise ValueError(f"unsupported retriever mode: {self.mode}")


@dataclass(frozen=True)
class SearchPlan:
    query: str
    app_id: str | None = None
    mode: str = "hybrid"
    top_k: int = 5
    rerank: bool = False
    fetch_k: int = 100
    dense_weight: float = 0.5
    sparse_weight: float = 0.5
    rrf_k: int = 60
    file_ids: list[str] | None = None

    def __post_init__(self):
        if self.mode not in ("dense", "sparse", "hybrid"):
            raise ValueError(f"unsupported search mode: {self.mode}")
        if self.file_ids is not None:
            if len(self.file_ids) == 0:
                raise ValueError("file_ids cannot be empty")
            if len(self.file_ids) > 1000:
                raise ValueError("file_ids exceeds max limit: 1000")


class _SearchExecutor:
    def __init__(
        self,
        plan: SearchPlan,
        rerank: Rerank | None = None,
        sparse: Sparse | None = None,
        store: Store | None = None,
        search_trace: bool = False,
    ):
        self.plan = plan
        self.rerank = rerank
        self.sparse = sparse
        self.store = store or _active_store()
        self.runner = SearchRunner()
        self._runtime_retrieve_limit = self.plan.top_k
        self.trace = SearchTrace(search_trace)

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
                "rerank": self.plan.rerank,
                "fetch_k": self.plan.fetch_k,
                "dense_weight": self.plan.dense_weight,
                "sparse_weight": self.plan.sparse_weight,
                "rrf_k": self.plan.rrf_k,
                "file_ids": list(self.plan.file_ids or []),
            },
        }

    def _build_runnable(self):
        return (
            RunnableLambda(self._prepare_plan, name="prepare_plan")
            | self._retrieve_runnable()
            | RunnableLambda(self._dedupe_items, name="dedupe")
            | RunnableLambda(self._rerank_if_needed, name="rerank")
            | RunnableLambda(self._format_response, name="format_response")
        )

    def _prepare_plan(self, _):
        with self.trace.stage("prepare_plan"):
            retrieve_limit = (
                _clamp_fetch_k(self.store, self.plan.fetch_k, self.plan.file_ids)
                if self.plan.rerank
                else self.plan.top_k
            )
            self._runtime_retrieve_limit = retrieve_limit
            return {
                "retrieve_limit": retrieve_limit,
                "metadata_filter": self.store.build_file_filter(self.plan.file_ids),
                "skip": False,
            }

    def _retrieve_runnable(self):
        if self.plan.mode == "sparse":
            return self._retriever("sparse") | RunnableLambda(_documents_to_items, name="sparse_items")
        if self.plan.mode == "hybrid":
            return (
                RunnableParallel(
                    dense=self._retriever("dense"),
                    sparse=self._retriever("sparse"),
                )
                | RunnableLambda(self._fuse_parts, name="fusion")
            )
        return self._retriever("dense") | RunnableLambda(_documents_to_items, name="dense_items")

    def _retriever(self, mode: str) -> _SearchRetriever:
        return _SearchRetriever(
            store=self.store,
            sparse=self.sparse,
            mode=mode,
            query=self.plan.query,
            trace=self.trace,
            name=mode,
        )

    def _fuse_parts(self, parts: dict[str, list[Document]]) -> list[dict]:
        with self.trace.stage("fusion") as stage:
            items = _weighted_reciprocal_rank(_documents_to_items(parts["dense"]), _documents_to_items(parts["sparse"]), self._runtime_retrieve_limit, self.plan)
            stage["count"] = len(items)
            return items

    def _retrieve_collection(self, metadata_filter, limit: int) -> list[dict]:
        if self.plan.mode == "sparse":
            return _retrieve_sparse(self.store, metadata_filter, self.plan.query, limit, self.sparse)
        if self.plan.mode == "hybrid":
            dense_items, sparse_items = self.runner.run_dense_and_sparse(
                lambda: _retrieve_dense(self.store, metadata_filter, self.plan.query, limit),
                lambda: _retrieve_sparse(self.store, metadata_filter, self.plan.query, limit, self.sparse),
            )
            return _weighted_reciprocal_rank(dense_items, sparse_items, limit, self.plan)
        return _retrieve_dense(self.store, metadata_filter, self.plan.query, limit)

    def _retrieve_dense_context(self, context: dict) -> list[dict]:
        return _retrieve_dense(self.store, context["metadata_filter"], self.plan.query, context["retrieve_limit"])

    def _retrieve_sparse_context(self, context: dict) -> list[dict]:
        return _retrieve_sparse(self.store, context["metadata_filter"], self.plan.query, context["retrieve_limit"], self.sparse)

    def _retrieve_store_hybrid_context(self, context: dict) -> list[dict]:
        return _retrieve_store_hybrid(self.store, context["metadata_filter"], self.plan.query, context["retrieve_limit"], self.plan)

    def _rerank(self, items: list[dict]) -> list[dict]:
        if self.rerank is None:
            raise RuntimeError("rerank is required when rerank is enabled")
        return self.rerank.rerank(self.plan.query, items, self.plan.top_k)

    def _dedupe_items(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("dedupe") as stage:
            deduped = _dedupe(items)
            stage["count"] = len(deduped)
            return deduped

    def _rerank_if_needed(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("rerank") as stage:
            if self.plan.rerank:
                reranked = self._rerank(self._filter_before_rerank(items))
                stage["count"] = len(reranked)
                return reranked
            if self.plan.mode == "dense":
                items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            elif self.plan.mode == "hybrid":
                items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            stage["count"] = len(items)
            return items

    def _format_response(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("format_response") as stage:
            results = [_public_item(item) for item in items[: self.plan.top_k]]
            stage["count"] = len(results)
            return results

    def _filter_before_rerank(self, items: list[dict]) -> list[dict]:
        if self.plan.mode == "sparse":
            return items
        if self.plan.mode == "hybrid":
            items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            return items
        items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        return items


def _retrieve_dense(store: Store, metadata_filter, query: str, limit: int) -> list[dict]:
    return store.search_dense(query, limit, metadata_filter)


def _retrieve_sparse(
    store: Store,
    metadata_filter,
    query: str,
    limit: int,
    sparse: Sparse | None = None,
) -> list[dict]:
    if store.sparse_uses_store(sparse):
        return _retrieve_store_sparse(store, metadata_filter, query, limit)
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    documents = store.get_search_documents(metadata_filter)
    if not sparse.ready:
        raise RuntimeError("sparse is not initialized")
    return sparse.search(query, documents, limit)


def _retrieve_store_sparse(store: Store, metadata_filter, query: str, limit: int) -> list[dict]:
    return store.search_sparse(query, limit, metadata_filter)


def _retrieve_store_hybrid(store: Store, metadata_filter, query: str, limit: int, plan: SearchPlan) -> list[dict]:
    return store.search_hybrid(query, limit, metadata_filter, plan.dense_weight, plan.sparse_weight, plan.rrf_k)


def _weighted_reciprocal_rank(dense_items: list[dict], sparse_items: list[dict], limit: int, plan: SearchPlan) -> list[dict]:
    rrf_k = plan.rrf_k
    dense_weight = plan.dense_weight
    sparse_weight = plan.sparse_weight
    by_id: dict[str, dict] = {}
    scores: dict[str, float] = {}
    for weight, items in ((dense_weight, dense_items), (sparse_weight, sparse_items)):
        for rank, item in enumerate(items, start=1):
            item_id = item["id"]
            by_id.setdefault(item_id, item)
            scores[item_id] = scores.get(item_id, 0.0) + weight / (rrf_k + rank)
    fused = []
    for item_id, score in scores.items():
        item = dict(by_id[item_id])
        item["_score"] = score
        fused.append(item)
    fused.sort(key=lambda item: item["_score"], reverse=True)
    return fused[:limit]


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        key = item.get("id") or (item.get("content"), tuple(sorted((item.get("metadata") or {}).items())))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _public_item(item: dict) -> dict:
    return {key: value for key, value in item.items() if not key.startswith("_")}


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


_default_store: Store | None = None


def set_default_store(store: Store) -> None:
    global _default_store
    _default_store = store


def _active_store() -> Store:
    if _default_store is None:
        raise RuntimeError("store is not initialized")
    return _default_store
