"""Qdrant-backed document storage and collection management."""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import defaultdict
from typing import Literal

from config import (
    DENSE_MODEL_DIR,
    QDRANT_CHUNKS_COLLECTION,
    QDRANT_URL,
)
from dense.base import Dense
from dense.huggingface import HuggingFaceDense
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sparse.base import Sparse
from store.files import count_files_from_documents, list_files_from_documents
from store.startup import run_with_startup_retry


SearchMode = Literal["dense", "sparse", "hybrid"]

_client: QdrantClient | None = None
_dense: Dense | None = None
_sparse: Sparse | None = None
_dense_vector_size: int | None = None
_timeout: int | None = None
_ready = False

_document_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_document_locks_guard = threading.Lock()


class QdrantStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        url: str | None = None,
        timeout: int | None = None,
        chunks_collection: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.url = url or QDRANT_URL
        self.timeout = timeout
        self.chunks_collection = chunks_collection or QDRANT_CHUNKS_COLLECTION

    def start(self) -> None:
        init_store(
            dense=self.dense,
            sparse=self.sparse,
            url=self.url,
            timeout=self.timeout,
            chunks_collection=self.chunks_collection,
        )

    def stop(self) -> None:
        close_store()

    def drop_collections(self) -> None:
        _configure_store(self.url, self.chunks_collection, self.timeout)
        drop_collections()

    @property
    def ready(self) -> bool:
        return is_search_ready()

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        return add_file_chunks(chunks, file_id)

    def delete_file_chunks(self, file_id: str) -> int:
        return delete_file_chunks(file_id)

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        return get_total_chunks(file_ids)

    def list_files(self, limit: int = 50, cursor: str | None = None):
        return list_files_from_documents(get_search_documents(None), limit=limit, cursor=cursor)

    def count_files(self) -> int:
        return count_files_from_documents(get_search_documents(None))

    def get_search_documents(self, metadata_filter: models.Filter) -> list[dict]:
        return get_search_documents(metadata_filter)

    def build_file_filter(self, file_ids: list[str] | None = None) -> models.Filter | None:
        return build_file_filter(file_ids)

    def search_dense(self, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return search_dense(query, limit, metadata_filter)

    def search_sparse(self, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return search_sparse(query, limit, metadata_filter)

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: models.Filter,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        return search_hybrid(query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        return _sparse_uses_store(sparse)


def close_store():
    """释放 Qdrant client;保留已加载的模型引用。"""
    global _client, _ready
    if _client is not None:
        close = getattr(_client, "close", None)
        if callable(close):
            close()
    _client = None
    _ready = False


def drop_collections() -> None:
    client = get_qdrant_client()
    if client.collection_exists(QDRANT_CHUNKS_COLLECTION):
        client.delete_collection(QDRANT_CHUNKS_COLLECTION)


def init_store(
    dense: Dense | None = None,
    sparse: Sparse | None = None,
    url: str | None = None,
    timeout: int | None = None,
    chunks_collection: str | None = None,
):
    """启动阶段完成存储运行时初始化;请求阶段不做懒初始化。"""
    global _ready
    _configure_store(url, chunks_collection, timeout)
    _init_dense(dense)
    _init_sparse(sparse)
    _init_dense_vector_size()
    run_with_startup_retry(ensure_collections)
    _ready = True


def init_search():
    init_store()


def _configure_store(
    url: str | None = None,
    chunks_collection: str | None = None,
    timeout: int | None = None,
):
    global QDRANT_URL, QDRANT_CHUNKS_COLLECTION, _timeout
    if url is not None:
        QDRANT_URL = url
    _timeout = timeout
    if chunks_collection is not None:
        QDRANT_CHUNKS_COLLECTION = chunks_collection


def is_search_ready() -> bool:
    return _ready


def _require_search_ready():
    if not _ready:
        raise RuntimeError("search is not initialized")


def _init_dense(dense: Dense | None = None) -> Dense:
    global _dense
    if _dense is None:
        _dense = dense or HuggingFaceDense()
    if not _dense.ready:
        raise RuntimeError("dense is not initialized")
    return _dense


def _init_dense_vector_size() -> int:
    global _dense_vector_size
    if _dense_vector_size is None:
        _dense_vector_size = len(_init_dense().embed_query("dimension probe"))
    return _dense_vector_size


def _init_sparse(sparse: Sparse | None = None) -> Sparse | None:
    global _sparse
    _sparse = sparse
    if _sparse is not None and not _sparse.ready:
        raise RuntimeError("sparse is not initialized")
    return _sparse


def _get_dense() -> Dense:
    if _dense is None:
        raise RuntimeError("search is not initialized")
    return _dense


def _get_sparse() -> Sparse | None:
    return _sparse


def _sparse_uses_store(sparse: Sparse | None = None) -> bool:
    from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    return isinstance(_get_sparse() if sparse is None else sparse, QdrantBGEM3Sparse)


def sparse_uses_store(sparse: Sparse | None = None) -> bool:
    return _sparse_uses_store(sparse)


def _get_dense_vector_size() -> int:
    if _dense_vector_size is None:
        raise RuntimeError("search is not initialized")
    return _dense_vector_size


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=os.getenv("QDRANT_URL", QDRANT_URL), timeout=_timeout, check_compatibility=False)
    return _client


def ensure_collections():
    client = get_qdrant_client()
    dense_size = _get_dense_vector_size()
    if client.collection_exists(QDRANT_CHUNKS_COLLECTION):
        _ensure_sparse_vector(client, QDRANT_CHUNKS_COLLECTION)
        ensure_payload_indexes()
        return
    sparse_vectors_config = (
        {"sparse": models.SparseVectorParams()}
        if _sparse_uses_store()
        else None
    )
    client.create_collection(
        collection_name=QDRANT_CHUNKS_COLLECTION,
        vectors_config={
            "dense": models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
        },
        sparse_vectors_config=sparse_vectors_config,
    )
    _wait_collection_ready(client, QDRANT_CHUNKS_COLLECTION)
    ensure_payload_indexes()


def _wait_collection_ready(client: QdrantClient, collection_name: str) -> None:
    deadline = time.monotonic() + 5
    last_error = None
    while time.monotonic() < deadline:
        try:
            client.get_collection(collection_name)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


def _ensure_sparse_vector(client: QdrantClient, collection_name: str) -> None:
    if not _sparse_uses_store():
        return
    collection = client.get_collection(collection_name)
    sparse_vectors = collection.config.params.sparse_vectors or {}
    if "sparse" in sparse_vectors:
        return
    client.update_collection(
        collection_name=collection_name,
        sparse_vectors_config={"sparse": models.SparseVectorParams()},
    )


def ensure_payload_indexes():
    client = get_qdrant_client()
    _ensure_payload_index(client, QDRANT_CHUNKS_COLLECTION, "metadata.file_id")


def _ensure_payload_index(client: QdrantClient, collection_name: str, field_name: str):
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except Exception:
        pass


def search_dense(query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
    return _query_points(_get_dense().embed_query(query), "dense", limit, metadata_filter)


def search_sparse(query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
    sparse = _get_sparse()
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    return _query_points(_qdrant_sparse_vector(sparse.embed_query(query)), "sparse", limit, metadata_filter)


def search_hybrid(
    query: str,
    limit: int,
    metadata_filter: models.Filter,
    dense_weight: float = 0.5,
    sparse_weight: float = 0.5,
    rrf_k: int = 60,
) -> list[dict]:
    dense_items = search_dense(query, limit, metadata_filter)
    sparse_items = search_sparse(query, limit, metadata_filter)
    return _weighted_reciprocal_rank(dense_items, sparse_items, limit, dense_weight, sparse_weight, rrf_k)


def _query_points(query, vector_name: str, limit: int, metadata_filter: models.Filter | None) -> list[dict]:
    _require_search_ready()
    response = get_qdrant_client().query_points(
        collection_name=QDRANT_CHUNKS_COLLECTION,
        query=query,
        using=vector_name,
        query_filter=metadata_filter,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [_point_to_item(point) for point in response.points]


def add_file_chunks(chunks: list[dict], file_id: str) -> int:
    if not chunks:
        return 0
    if not file_id:
        raise ValueError("file_id is required")
    _require_search_ready()
    with _document_lock(file_id):
        delete_file_chunks(file_id)
        get_qdrant_client().upsert(
            collection_name=QDRANT_CHUNKS_COLLECTION,
            points=_to_points(chunks, file_id),
        )
    return len(chunks)


def delete_file_chunks(file_id: str) -> int:
    return _delete_by_filter(_file_payload_filter(file_ids=[file_id]))


def get_total_chunks(file_ids: list[str] | None = None) -> int:
    return _count_documents(build_file_filter(file_ids))


def get_search_documents(metadata_filter: models.Filter | None) -> list[dict]:
    client = get_qdrant_client()
    documents = []
    offset = None
    while True:
        rows, offset = client.scroll(
            collection_name=QDRANT_CHUNKS_COLLECTION,
            scroll_filter=metadata_filter,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for row in rows:
            payload = row.payload or {}
            metadata = _metadata_from_payload(payload)
            content = payload.get("page_content") or payload.get("content") or ""
            documents.append({
                "id": str(row.id),
                "content": content,
                "metadata": metadata,
            })
        if offset is None:
            break
    return documents


def build_file_filter(file_ids: list[str] | None = None) -> models.Filter | None:
    if file_ids is None:
        return None
    if not file_ids:
        raise ValueError("file_ids cannot be empty")
    return _file_payload_filter(file_ids=file_ids)


def _to_points(chunks: list[dict], file_id: str) -> list[models.PointStruct]:
    contents = [chunk["content"] for chunk in chunks]
    dense_vectors = _get_dense().embed_documents(contents)
    sparse_vectors = _sparse_vectors_for_documents(contents) if _sparse_uses_store() else [None] * len(chunks)
    points = []
    for chunk, dense_vector, sparse_vector in zip(chunks, dense_vectors, sparse_vectors):
        point_id = _point_id(chunk["id"])
        vector = {"dense": dense_vector}
        if sparse_vector is not None:
            vector["sparse"] = sparse_vector
        points.append(models.PointStruct(id=point_id, vector=vector, payload=_payload_for_chunk(chunk, file_id)))
    return points


def _payload_for_chunk(chunk: dict, file_id: str) -> dict:
    metadata = dict(chunk.get("metadata") or {})
    metadata["file_id"] = file_id
    if "chunk_index" not in metadata:
        raise ValueError("chunk metadata.chunk_index is required")
    if not metadata.get("filename"):
        raise ValueError("chunk metadata.filename is required")
    return {
        "content": chunk["content"],
        "metadata": metadata,
    }


def _sparse_vectors_for_documents(texts: list[str]) -> list[models.SparseVector]:
    sparse = _get_sparse()
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    return [_qdrant_sparse_vector(vector) for vector in sparse.embed_documents(texts)]


def _qdrant_sparse_vector(vector) -> models.SparseVector:
    return models.SparseVector(indices=list(vector.indices), values=list(vector.values))


def _file_payload_filter(file_ids: list[str]) -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="metadata.file_id", match=models.MatchAny(any=file_ids)),
    ])


def _delete_by_filter(metadata_filter: models.Filter) -> int:
    client = get_qdrant_client()
    before = _count_documents(metadata_filter)
    if before:
        client.delete(collection_name=QDRANT_CHUNKS_COLLECTION, points_selector=models.FilterSelector(filter=metadata_filter))
    return before


def _count_documents(metadata_filter: models.Filter | None) -> int:
    client = get_qdrant_client()
    result = client.count(collection_name=QDRANT_CHUNKS_COLLECTION, count_filter=metadata_filter, exact=True)
    return int(result.count)


def _point_to_item(point) -> dict:
    payload = dict(point.payload or {})
    return {
        "id": str(point.id),
        "content": payload.get("content") or payload.get("page_content") or "",
        "metadata": _metadata_from_payload(payload),
        "_score": float(point.score),
    }


def _weighted_reciprocal_rank(
    dense_items: list[dict],
    sparse_items: list[dict],
    limit: int,
    dense_weight: float = 0.5,
    sparse_weight: float = 0.5,
    rrf_k: int = 60,
) -> list[dict]:
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


def _metadata_from_payload(payload: dict | None) -> dict:
    if not payload:
        return {}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return payload


def _document_lock(file_id: str):
    with _document_locks_guard:
        return _document_locks[file_id]


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
