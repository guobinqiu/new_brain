"""Search plan and execution pipeline."""
from __future__ import annotations

from dataclasses import dataclass

from config import SEARCH_CONFIG
from rerank.base import Rerank
from search.runner import SearchRunner
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
        self.sparse.start()
        self.ready = True

    def stop(self) -> None:
        self.sparse.stop()
        self.ready = False


def init_search():
    BM25Sparse().start()


def init_search_pipeline():
    init_search()


def _clamp_fetch_k(store: Store, fetch_k: int, namespace: str, scope_ids: list[str]) -> int:
    """把候选池宽度限制到 [1, 当前查询范围总 chunk 数]。"""
    total = store.get_total_chunks(namespace=namespace, scope_ids=scope_ids)
    if total <= 0:
        return 1
    return max(1, min(fetch_k, total))


@dataclass(frozen=True)
class SearchPlan:
    query: str
    mode: str = "hybrid"
    top_k: int = 5
    rerank: bool = False
    fetch_k: int = 100
    namespace: str = "default"
    scope_ids: list[str] | None = None

    def __post_init__(self):
        if self.mode not in ("dense", "sparse", "hybrid"):
            raise ValueError(f"unsupported search mode: {self.mode}")
        if self.scope_ids is None:
            object.__setattr__(self, "scope_ids", [])


class _SearchExecutor:
    def __init__(
        self,
        plan: SearchPlan,
        rerank: Rerank | None = None,
        sparse: Sparse | None = None,
        store: Store | None = None,
    ):
        self.plan = plan
        self.rerank = rerank
        self.sparse = sparse
        self.store = store or _active_store()
        self.runner = SearchRunner()

    def execute(self) -> list[dict]:
        retrieve_limit = (
            _clamp_fetch_k(self.store, self.plan.fetch_k, self.plan.namespace, self.plan.scope_ids)
            if self.plan.rerank
            else self.plan.top_k
        )
        common_items, scoped_items = self._retrieve_candidates(retrieve_limit)
        items = _dedupe(scoped_items + common_items)

        if self.plan.rerank:
            items = self._filter_before_rerank(items)
            return self._rerank(items)
        if self.plan.mode == "dense":
            items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        elif self.plan.mode == "hybrid":
            items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        return [_public_item(item) for item in items[: self.plan.top_k]]

    def _retrieve_candidates(self, limit: int) -> tuple[list[dict], list[dict]]:
        common_fn = lambda: self._retrieve_collection("common", self.store.build_common_filter(self.plan.namespace), limit)
        scoped_fn = (
            lambda: self._retrieve_collection("scoped", self.store.build_scoped_filter(self.plan.namespace, self.plan.scope_ids), limit)
            if self.plan.scope_ids
            else None
        )
        return self.runner.run_common_and_scoped(common_fn, scoped_fn)

    def _retrieve_collection(self, collection_type: str, metadata_filter, limit: int) -> list[dict]:
        if self.plan.mode == "sparse":
            return _retrieve_sparse(self.store, collection_type, metadata_filter, self.plan.query, limit, self.sparse)
        if self.plan.mode == "hybrid":
            if self.store.sparse_uses_store(self.sparse):
                return _retrieve_store_hybrid(self.store, collection_type, metadata_filter, self.plan.query, limit)
            dense_items, sparse_items = self.runner.run_dense_and_sparse(
                lambda: _retrieve_dense(self.store, collection_type, metadata_filter, self.plan.query, limit),
                lambda: _retrieve_sparse(self.store, collection_type, metadata_filter, self.plan.query, limit, self.sparse),
            )
            return _weighted_reciprocal_rank(dense_items, sparse_items, limit)
        return _retrieve_dense(self.store, collection_type, metadata_filter, self.plan.query, limit)

    def _rerank(self, items: list[dict]) -> list[dict]:
        if self.rerank is None:
            raise RuntimeError("rerank is required when rerank is enabled")
        return self.rerank.rerank(self.plan.query, items, self.plan.top_k)

    def _filter_before_rerank(self, items: list[dict]) -> list[dict]:
        if self.plan.mode == "sparse":
            return items
        if self.plan.mode == "hybrid":
            items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
            return items
        items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        return items


def _retrieve_dense(store: Store, collection_type: str, metadata_filter, query: str, limit: int) -> list[dict]:
    return store.search_dense(collection_type, query, limit, metadata_filter)


def _retrieve_sparse(
    store: Store,
    collection_type: str,
    metadata_filter,
    query: str,
    limit: int,
    sparse: Sparse | None = None,
) -> list[dict]:
    if store.sparse_uses_store(sparse):
        return _retrieve_store_sparse(store, collection_type, metadata_filter, query, limit)
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    documents = store.get_search_documents(collection_type, metadata_filter)
    if not sparse.ready:
        raise RuntimeError("sparse is not initialized")
    return sparse.search(query, documents, limit)


def _retrieve_store_sparse(store: Store, collection_type: str, metadata_filter, query: str, limit: int) -> list[dict]:
    return store.search_sparse(collection_type, query, limit, metadata_filter)


def _retrieve_store_hybrid(store: Store, collection_type: str, metadata_filter, query: str, limit: int) -> list[dict]:
    return store.search_hybrid(collection_type, query, limit, metadata_filter)


def _weighted_reciprocal_rank(dense_items: list[dict], sparse_items: list[dict], limit: int) -> list[dict]:
    rrf_k = SEARCH_CONFIG.get("rrf_k", 60)
    dense_weight = SEARCH_CONFIG.get("dense_weight", 0.5)
    sparse_weight = SEARCH_CONFIG.get("sparse_weight", 0.5)
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


_default_store: Store | None = None


def set_default_store(store: Store) -> None:
    global _default_store
    _default_store = store


def _active_store() -> Store:
    if _default_store is None:
        raise RuntimeError("store is not initialized")
    return _default_store
