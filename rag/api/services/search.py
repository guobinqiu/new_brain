from fastapi import HTTPException

from rag.api.runtime import runtime
from rag.api.schemas import DebugEncodeRequest, DebugSearchRequest, SearchRequest
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


def debug_dense_encode(app_id: str, req: DebugEncodeRequest, principal):
    require_ready()
    database_principal(principal, app_id)
    vector = runtime.application.dense.embed_query(req.query)
    return {
        "type": "dense",
        "query": req.query,
        "query_vector": _dense_vector(vector),
    }


def debug_sparse_encode(app_id: str, req: DebugEncodeRequest, principal):
    require_ready()
    database_principal(principal, app_id)
    sparse = runtime.application.sparse
    if sparse is None:
        raise HTTPException(status_code=400, detail="sparse is not enabled")
    embed_query = getattr(sparse, "embed_query", None)
    if not callable(embed_query):
        raise HTTPException(status_code=400, detail="sparse vector encoding is not supported by current sparse backend")
    vector = embed_query(req.query)
    return {
        "type": "sparse",
        "query": req.query,
        "query_vector": _sparse_vector(vector),
    }


def debug_dense_search(app_id: str, req: DebugSearchRequest, principal):
    require_ready()
    search_principal = database_principal(principal, app_id)
    vector = runtime.application.dense.embed_query(req.query)
    store = scoped_store(search_principal)
    metadata_filter = store.build_file_filter(req.file_ids)
    results = store.search_dense(req.query, req.top_k, metadata_filter)
    return {
        "type": "dense",
        "query": req.query,
        "query_vector": _dense_vector(vector),
        "results": [_debug_result(result) for result in results],
    }


def debug_sparse_search(app_id: str, req: DebugSearchRequest, principal):
    require_ready()
    sparse = runtime.application.sparse
    if sparse is None:
        raise HTTPException(status_code=400, detail="sparse is not enabled")
    embed_query = getattr(sparse, "embed_query", None)
    if not callable(embed_query):
        raise HTTPException(status_code=400, detail="sparse vector encoding is not supported by current sparse backend")
    search_principal = database_principal(principal, app_id)
    vector = embed_query(req.query)
    store = scoped_store(search_principal)
    metadata_filter = store.build_file_filter(req.file_ids)
    results = store.search_sparse(req.query, req.top_k, metadata_filter)
    return {
        "type": "sparse",
        "query": req.query,
        "query_vector": _sparse_vector(vector),
        "results": [_debug_result(result) for result in results],
    }


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


def _sparse_vector(vector) -> dict:
    indices = getattr(vector, "indices", None)
    values = getattr(vector, "values", None)
    if indices is None and isinstance(vector, dict):
        items = sorted((int(index), float(value)) for index, value in vector.items())
    else:
        items = sorted((int(index), float(value)) for index, value in zip(indices or [], values or []))
    return {
        "indices": [index for index, _ in items],
        "values": [value for _, value in items],
    }
