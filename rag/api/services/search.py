from fastapi import HTTPException

from rag.api.runtime import runtime
from rag.api.schemas import SearchRequest
from rag.api.services.common import database_principal, require_ready, scoped_store
from rag.search import SearchPlan, _SearchExecutor


def client_search(req: SearchRequest, principal):
    response = _search(req, principal)
    response["results"] = [_client_result(result) for result in response["results"]]
    return response


def search(req: SearchRequest, principal):
    response = _search(req, principal)
    if principal.type == "app":
        response["results"] = [_client_result(result) for result in response["results"]]
    return response


def _search(req: SearchRequest, principal):
    require_ready()
    search_principal = database_principal(principal, req.app_id)
    if req.mode in {"sparse", "hybrid"} and runtime.application.sparse is None:
        raise HTTPException(status_code=400, detail="sparse is not enabled")
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


def _client_result(result: dict) -> dict:
    return {
        "id": result.get("id"),
        "content": result.get("content", ""),
        "score": result.get("score"),
    }
