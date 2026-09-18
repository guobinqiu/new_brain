import logging

from fastapi import HTTPException

from services.rag.core.api.schemas import DebugEncodeRequest, DebugSearchRequest, SearchRequest
from services.rag.core.api.services.common import database_principal, require_ready, scoped_vector
from services.rag.core.search import SearchPlan, _SearchExecutor
from shared.upstream import UpstreamServiceError


logger = logging.getLogger(__name__)


def client_search(state, req: SearchRequest, principal):
    response = _search(state, req, principal)
    response["results"] = [_client_result(result) for result in response["results"]]
    return response


def search(state, req: SearchRequest, principal):
    response = _search(state, req, principal)
    if principal.type == "app":
        response["results"] = [_client_result(result) for result in response["results"]]
    return response


def debug_dense_encode(state, app_id: str, req: DebugEncodeRequest, principal):
    require_ready(state)
    database_principal(principal, app_id)
    vector = state.inference_client.dense.embed_query(req.query)
    return {
        "type": "dense",
        "query": req.query,
        "query_vector": _dense_vector(vector),
    }


def debug_dense_search(state, app_id: str, req: DebugSearchRequest, principal):
    require_ready(state)
    search_principal = database_principal(principal, app_id)
    query_vector = state.inference_client.dense.embed_query(req.query)
    vector_client = scoped_vector(state, search_principal)
    metadata_filter = vector_client.build_file_filter(req.file_ids)
    results = vector_client.query_dense_vector(query_vector, req.top_k, metadata_filter)
    return {
        "type": "dense",
        "query": req.query,
        "query_vector": _dense_vector(query_vector),
        "results": [_debug_result(result) for result in results],
    }


def _search(state, req: SearchRequest, principal):
    require_ready(state)
    search_principal = database_principal(principal, req.app_id)
    rerank_enabled = state.config.search.rerank if req.rerank is None else req.rerank
    plan = SearchPlan(
        req.query,
        app_id=search_principal.app_id,
        mode=req.mode or state.config.search.mode,
        top_k=req.top_k or state.config.search.top_k,
        rerank_fetch_k=req.rerank_fetch_k or state.config.search.rerank_fetch_k,
        rerank=rerank_enabled,
        rrf_k=req.rrf_k or state.config.search.rrf_k,
        file_ids=req.file_ids,
    )
    vector = scoped_vector(state, search_principal)
    sparse_ready = getattr(vector, "supports_sparse_vector", lambda: False)()
    if plan.mode == "sparse" and not sparse_ready:
        raise HTTPException(status_code=400, detail="sparse search is not configured")
    if plan.mode == "hybrid" and not sparse_ready:
        plan = SearchPlan(
            plan.query,
            app_id=plan.app_id,
            mode="dense",
            top_k=plan.top_k,
            rerank_fetch_k=plan.rerank_fetch_k,
            rerank=plan.rerank,
            rrf_k=plan.rrf_k,
            file_ids=plan.file_ids,
        )
    rerank_client = getattr(state.inference_client, "rerank", None)
    if plan.rerank and rerank_client is None:
        plan = SearchPlan(
            plan.query,
            app_id=plan.app_id,
            mode=plan.mode,
            top_k=plan.top_k,
            rerank_fetch_k=plan.rerank_fetch_k,
            rerank=False,
            rrf_k=plan.rrf_k,
            file_ids=plan.file_ids,
        )
    executor = _SearchExecutor(
        plan,
        vector=vector,
        rerank=rerank_client,
        vector_backend=state.vector_backend,
        search_trace=state.config.logging.search_trace,
    )
    try:
        results = executor.execute()
    except UpstreamServiceError as exc:
        logger.exception("Search failed", extra={"trace_id": exc.trace_id})
        raise
    except HTTPException:
        raise
    except Exception as exc:
        error = UpstreamServiceError(service="rag", error=str(exc), retryable=False, status_code=500)
        logger.exception("Search failed", extra={"trace_id": error.trace_id})
        raise error from exc
    elapsed_ms = executor.trace.result["elapsed_ms"] if executor.trace.result else 0
    return {
        "results": results,
        "mode": plan.mode,
        "rerank": plan.rerank,
        "rerank_fetch_k": plan.rerank_fetch_k if plan.rerank else None,
        "elapsed_ms": elapsed_ms,
    }


def _client_result(result: dict) -> dict:
    return {
        "id": result.get("id"),
        "content": result.get("content", ""),
        "score": result.get("score"),
    }


def _debug_result(result: dict) -> dict:
    metadata = dict(result.get("metadata") or {})
    return {
        "id": result.get("id"),
        "content": result.get("content", ""),
        "score": result.get("score", result.get("_score")),
        "file_id": metadata.get("file_id"),
        "filename": metadata.get("filename"),
        "chunk_index": metadata.get("chunk_index"),
        "s3_url": metadata.get("s3_url"),
    }


def _dense_vector(vector) -> list[float]:
    return [float(value) for value in vector]
