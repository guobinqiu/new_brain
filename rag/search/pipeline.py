"""Search plan and execution pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda, RunnableParallel
from pydantic import ConfigDict
from rag.rerank.base import Rerank
from rag.search.runner import SearchRunner
from rag.search.trace import SearchTrace
from rag.sparse.base import Sparse
from rag.sparse.simple_bm25 import SimpleBM25Sparse
from rag.store.base import Store


class SearchPipeline:
    def __init__(self, store: Store, sparse: Sparse | None = None):
        self.store = store
        self.sparse = sparse
        self.ready = False

    def start(self) -> None:
        if self.sparse is not None and not self.sparse.ready:
            raise RuntimeError("sparse is not initialized")
        self.ready = True

    def stop(self) -> None:
        self.ready = False


def init_search():
    SimpleBM25Sparse().start()


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
        stage_name = self.mode
        if self.trace is None:
            items = self._retrieve_items(context)
        else:
            with self.trace.stage(stage_name, **self._trace_fields()) as stage:
                items = self._retrieve_items(context)
                stage["count"] = len(items)
                stage["hit_count"] = len(items)
        return [_item_to_document(item) for item in items]

    def _trace_fields(self) -> dict[str, str]:
        if self.mode == "dense":
            return {"backend": _store_backend(self.store), "retriever": "dense"}
        if self.mode == "sparse":
            if self.sparse is not None and self.store.sparse_uses_store(self.sparse):
                return {"backend": _store_backend(self.store), "retriever": "sparse_vector"}
            return {
                "backend": getattr(self.sparse, "backend", "app"),
                "retriever": getattr(self.sparse, "retriever", "bm25"),
            }
        if self.mode == "sparse_vector":
            return {"backend": _store_backend(self.store), "retriever": "sparse_vector"}
        if self.mode == "hybrid":
            return {"backend": _store_backend(self.store), "retriever": "hybrid"}
        return {"backend": "unknown", "retriever": self.mode}

    def _retrieve_items(self, context: dict[str, Any]) -> list[dict]:
        if self.mode == "dense":
            return _retrieve_dense(self.store, context["metadata_filter"], self.query, context["retrieve_limit"], self.trace)
        if self.mode == "sparse":
            return _retrieve_sparse(self.store, context["metadata_filter"], self.query, context["retrieve_limit"], self.sparse, self.app_id, self.file_ids, self.trace)
        if self.mode == "sparse_vector":
            return _retrieve_sparse(self.store, context["metadata_filter"], self.query, context["retrieve_limit"], self.sparse, self.app_id, self.file_ids, self.trace)
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
        if self.dense_weight + self.sparse_weight > 1:
            raise ValueError("search weights must be less than or equal to 1")
        if self.file_ids is not None:
            if len(self.file_ids) == 0:
                raise ValueError("file_ids cannot be empty")
            if len(self.file_ids) > 1000:
                raise ValueError("file_ids exceeds max limit: 1000")


class _SearchExecutor:
    def __init__(
        self,
        plan: SearchPlan,
        store: Store,
        rerank: Rerank | None = None,
        sparse: Sparse | None = None,
        search_trace: bool = False,
    ):
        self.plan = plan
        self.rerank = rerank
        self.sparse = sparse
        self.store = store
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
            self._validate_sparse_backend()
            retrievers = {
                "dense": self._retriever("dense"),
                "sparse": self._retriever("sparse"),
            }
            return (
                RunnableParallel(**retrievers)
                | RunnableLambda(self._fuse_parts, name="fusion")
            )
        return self._retriever("dense") | RunnableLambda(_documents_to_items, name="dense_items")

    def _retriever(self, mode: str) -> _SearchRetriever:
        return _SearchRetriever(
            store=self.store,
            sparse=self.sparse,
            mode=mode,
            query=self.plan.query,
            app_id=self.plan.app_id,
            file_ids=self.plan.file_ids,
            trace=self.trace,
            name=mode,
        )

    def _fuse_parts(self, parts: dict[str, list[Document]]) -> list[dict]:
        with self.trace.stage("fusion", backend="app", retriever="fusion") as stage:
            weighted_parts = []
            if "dense" in parts:
                weighted_parts.append((self.plan.dense_weight, _documents_to_items(parts["dense"])))
            if "sparse" in parts:
                weighted_parts.append((self.plan.sparse_weight, _documents_to_items(parts["sparse"])))
            items = _weighted_reciprocal_rank(weighted_parts, self._runtime_retrieve_limit, self.plan.rrf_k)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items

    def _validate_sparse_backend(self) -> None:
        if self.sparse is None:
            raise RuntimeError("sparse is not initialized")

    def _retrieve_collection(self, metadata_filter, limit: int) -> list[dict]:
        if self.plan.mode == "sparse":
            return _retrieve_sparse(self.store, metadata_filter, self.plan.query, limit, self.sparse, self.plan.app_id, self.plan.file_ids)
        if self.plan.mode == "hybrid":
            self._validate_sparse_backend()
            dense_items, sparse_items = self.runner.run_dense_and_sparse(
                lambda: _retrieve_dense(self.store, metadata_filter, self.plan.query, limit),
                lambda: _retrieve_sparse(self.store, metadata_filter, self.plan.query, limit, self.sparse, self.plan.app_id, self.plan.file_ids),
            )
            return _weighted_reciprocal_rank(((self.plan.dense_weight, dense_items), (self.plan.sparse_weight, sparse_items)), limit, self.plan.rrf_k)
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
        with self.trace.stage("dedupe", backend="app", retriever="dedupe") as stage:
            deduped = _dedupe(items)
            stage["count"] = len(deduped)
            stage["hit_count"] = len(deduped)
            return deduped

    def _rerank_if_needed(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("rerank", backend="model" if self.plan.rerank else "app", retriever="rerank") as stage:
            if self.plan.rerank:
                reranked = self._rerank(self._filter_before_rerank(items))
                stage["count"] = len(reranked)
                stage["hit_count"] = len(reranked)
                return reranked
            if self.plan.mode == "dense":
                items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            elif self.plan.mode == "hybrid":
                items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items

    def _format_response(self, items: list[dict]) -> list[dict]:
        with self.trace.stage("format_response", backend="app", retriever="format") as stage:
            results = [_public_item(item) for item in items[: self.plan.top_k]]
            stage["count"] = len(results)
            stage["hit_count"] = len(results)
            return results

    def _filter_before_rerank(self, items: list[dict]) -> list[dict]:
        if self.plan.mode == "sparse":
            return items
        if self.plan.mode == "hybrid":
            items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            return items
        items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        return items


def _retrieve_dense(store: Store, metadata_filter, query: str, limit: int, trace=None) -> list[dict]:
    if hasattr(store, "encode_dense_query") and hasattr(store, "query_dense_vector"):
        with _optional_stage(trace, "dense_encode", backend="model", retriever="dense") as stage:
            query_vector = store.encode_dense_query(query)
            stage["dimension"] = len(query_vector) if hasattr(query_vector, "__len__") else None
        with _optional_stage(trace, "dense_query", backend=_store_backend(store), retriever="dense") as stage:
            items = store.query_dense_vector(query_vector, limit, metadata_filter)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items
    return store.search_dense(query, limit, metadata_filter)


def _retrieve_sparse(
    store: Store,
    metadata_filter,
    query: str,
    limit: int,
    sparse: Sparse | None = None,
    app_id: str | None = None,
    file_ids: list[str] | None = None,
    trace=None,
) -> list[dict]:
    if store.sparse_uses_store(sparse):
        return _retrieve_store_sparse(store, metadata_filter, query, limit, trace)
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    search_index = getattr(sparse, "search_index", None)
    if search_index is not None:
        with _optional_stage(trace, "sparse_query", backend=getattr(sparse, "backend", "app"), retriever=getattr(sparse, "retriever", "bm25")) as stage:
            items = search_index(query, limit, app_id=app_id, file_ids=file_ids)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items
    documents = store.get_search_documents(metadata_filter)
    if not sparse.ready:
        raise RuntimeError("sparse is not initialized")
    with _optional_stage(trace, "sparse_query", backend=getattr(sparse, "backend", "app"), retriever=getattr(sparse, "retriever", "bm25")) as stage:
        items = sparse.search(query, documents, limit)
        stage["count"] = len(items)
        stage["hit_count"] = len(items)
        return items


def _retrieve_store_sparse(store: Store, metadata_filter, query: str, limit: int, trace=None) -> list[dict]:
    if hasattr(store, "encode_sparse_query") and hasattr(store, "query_sparse_vector"):
        with _optional_stage(trace, "sparse_encode") as stage:
            query_vector = store.encode_sparse_query(query)
            stage.update(_sparse_encode_fields(query_vector))
        with _optional_stage(trace, "sparse_query", backend=_store_backend(store), retriever=_sparse_retriever(query_vector)) as stage:
            items = store.query_sparse_vector(query_vector, limit, metadata_filter)
            stage["count"] = len(items)
            stage["hit_count"] = len(items)
            return items
    return store.search_sparse(query, limit, metadata_filter)


def _retrieve_store_hybrid(store: Store, metadata_filter, query: str, limit: int, plan: SearchPlan) -> list[dict]:
    return store.search_hybrid(query, limit, metadata_filter, plan.dense_weight, plan.sparse_weight, plan.rrf_k)


def _weighted_reciprocal_rank(weighted_parts, limit: int, rrf_k: int) -> list[dict]:
    by_id: dict[str, dict] = {}
    scores: dict[str, float] = {}
    for weight, items in weighted_parts:
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


def _sparse_dimension(vector) -> int | None:
    indices = getattr(vector, "indices", None)
    if indices is None and isinstance(vector, dict):
        indices = vector.get("indices") or vector.keys()
    return len(indices) if indices is not None else None


def _sparse_encode_fields(vector) -> dict[str, Any]:
    if isinstance(vector, str):
        return {"backend": "app", "retriever": "query"}
    return {"backend": "model", "retriever": "sparse_vector", "dimension": _sparse_dimension(vector)}


def _sparse_retriever(vector) -> str:
    return "bm25" if isinstance(vector, str) else "sparse_vector"


def _store_backend(store: Store) -> str:
    store_type = getattr(store, "type", None)
    if store_type:
        return str(store_type)
    name = store.__class__.__name__.lower()
    if "qdrant" in name or name == "fakestore":
        return "qdrant"
    if "milvus" in name:
        return "milvus"
    if "chroma" in name:
        return "chroma"
    return name.removesuffix("store") or "unknown"
