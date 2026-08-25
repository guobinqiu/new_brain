from api.runtime import runtime
from api.schemas import SearchRequest
from api.services.common import database_principal, require_ready, scoped_store
from search import SearchPlan, _SearchExecutor


def client_search(req: SearchRequest, principal):
    return _search(req, principal)


def search(req: SearchRequest, principal):
    return _search(req, principal)


def _search(req: SearchRequest, principal):
    require_ready()
    search_principal = database_principal(principal, req.app_id)
    effective_rerank = bool(req.rerank and runtime.application.rerank is not None)
    plan = SearchPlan(
        req.query,
        app_id=search_principal.app_id,
        mode=req.mode,
        top_k=req.top_k,
        rerank=effective_rerank,
        fetch_k=req.fetch_k,
        dense_weight=req.dense_weight,
        sparse_weight=req.sparse_weight,
        rrf_k=req.rrf_k,
        file_ids=req.file_ids,
    )
    executor = _SearchExecutor(
        plan,
        rerank=runtime.application.rerank,
        sparse=runtime.application.sparse,
        store=scoped_store(search_principal),
        search_trace=runtime.application.config.logging.search_trace,
    )
    results = executor.execute()
    elapsed_ms = executor.trace.result["elapsed_ms"] if executor.trace.result else 0
    return {
        "results": results,
        "mode": req.mode,
        "rerank": effective_rerank,
        "fetch_k": req.fetch_k,
        "dense_weight": req.dense_weight,
        "sparse_weight": req.sparse_weight,
        "rrf_k": req.rrf_k,
        "elapsed_ms": elapsed_ms,
    }
