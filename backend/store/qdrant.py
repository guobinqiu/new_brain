"""Qdrant-backed document storage and collection management."""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from config import (
    DENSE_MODEL_DIR,
    QDRANT_COMMON_COLLECTION,
    QDRANT_SCOPED_COLLECTION,
    QDRANT_URL,
)
from dense.base import Dense
from dense.huggingface import HuggingFaceDense
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from langchain_qdrant.sparse_embeddings import SparseEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sparse.base import Sparse


CollectionType = Literal["common", "scoped"]
SearchMode = Literal["dense", "sparse", "hybrid"]

COLLECTION_BY_TYPE: dict[CollectionType, str] = {
    "common": QDRANT_COMMON_COLLECTION,
    "scoped": QDRANT_SCOPED_COLLECTION,
}

RETRIEVAL_MODE_BY_SEARCH_MODE: dict[SearchMode, RetrievalMode] = {
    "dense": RetrievalMode.DENSE,
    "sparse": RetrievalMode.DENSE,
    "hybrid": RetrievalMode.DENSE,
}

_client: QdrantClient | None = None
_dense: Dense | None = None
_sparse: Sparse | None = None
_stores: dict[tuple[CollectionType, SearchMode], QdrantVectorStore] = {}
_dense_vector_size: int | None = None
_timeout: int | None = None
_ready = False
_STARTUP_RETRY_COUNT = 30
_STARTUP_RETRY_DELAY_SECONDS = 1

_document_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_document_locks_guard = threading.Lock()


class QdrantStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        url: str | None = None,
        timeout: int | None = None,
        common_collection: str | None = None,
        scoped_collection: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.url = url or QDRANT_URL
        self.timeout = timeout
        self.common_collection = common_collection or QDRANT_COMMON_COLLECTION
        self.scoped_collection = scoped_collection or QDRANT_SCOPED_COLLECTION

    def start(self) -> None:
        self.dense.start()
        init_store(
            dense=self.dense,
            sparse=self.sparse,
            url=self.url,
            timeout=self.timeout,
            common_collection=self.common_collection,
            scoped_collection=self.scoped_collection,
        )

    def stop(self) -> None:
        close_store()
        self.dense.stop()

    def drop_collections(self) -> None:
        _configure_store(self.url, self.common_collection, self.scoped_collection, self.timeout)
        drop_collections()

    @property
    def ready(self) -> bool:
        return is_search_ready()

    def add_common_documents(self, chunks: list[dict], namespace: str = "default") -> int:
        return add_common_documents(chunks, namespace)

    def add_scoped_documents(self, chunks: list[dict], namespace: str = "default", scope_id: str | None = None) -> int:
        return add_scoped_documents(chunks, namespace, scope_id)

    def delete_common_document(self, filename: str, namespace: str = "default") -> int:
        return delete_common_document(filename, namespace)

    def delete_scoped_document(self, filename: str, namespace: str = "default", scope_id: str | None = None) -> int:
        return delete_scoped_document(filename, namespace, scope_id)

    def list_documents(
        self,
        collection_type: Literal["all", "common", "scoped"] = "all",
        namespace: str = "default",
        scope_ids: list[str] | None = None,
    ) -> list[dict]:
        return list_documents(collection_type, namespace, scope_ids)

    def get_total_chunks(self, namespace: str = "default", scope_ids: list[str] | None = None) -> int:
        return get_total_chunks(namespace, scope_ids)

    def get_search_documents(self, collection_type: CollectionType, metadata_filter: models.Filter) -> list[dict]:
        return get_search_documents(collection_type, metadata_filter)

    def build_common_filter(self, namespace: str) -> models.Filter:
        return build_common_filter(namespace)

    def build_scoped_filter(self, namespace: str, scope_ids: list[str]) -> models.Filter:
        return build_scoped_filter(namespace, scope_ids)

    def search_dense(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return search_dense(collection_type, query, limit, metadata_filter)

    def search_sparse(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return search_sparse(collection_type, query, limit, metadata_filter)

    def search_hybrid(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return search_hybrid(collection_type, query, limit, metadata_filter)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        return _sparse_uses_store(sparse)


def close_store():
    """释放 Qdrant client 和 LangChain store 缓存;保留已加载的模型引用。"""
    global _client, _ready
    _stores.clear()
    if _client is not None:
        close = getattr(_client, "close", None)
        if callable(close):
            close()
    _client = None
    _ready = False


def drop_collections() -> None:
    client = get_qdrant_client()
    for collection_name in COLLECTION_BY_TYPE.values():
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name)
    _stores.clear()


def init_store(
    dense: Dense | None = None,
    sparse: Sparse | None = None,
    url: str | None = None,
    timeout: int | None = None,
    common_collection: str | None = None,
    scoped_collection: str | None = None,
):
    """启动阶段完成存储运行时初始化;请求阶段不做懒初始化。"""
    global _ready
    _configure_store(url, common_collection, scoped_collection, timeout)
    _init_dense(dense)
    _init_sparse(sparse)
    _init_dense_vector_size()
    _run_with_startup_retry(ensure_collections)
    _get_store_unchecked("common", "dense")
    _get_store_unchecked("scoped", "dense")
    if _sparse_uses_store():
        _get_store_unchecked("common", "sparse")
        _get_store_unchecked("scoped", "sparse")
        _get_store_unchecked("common", "hybrid")
        _get_store_unchecked("scoped", "hybrid")
    _ready = True


def init_search():
    init_store()


def _run_with_startup_retry(operation):
    last_error = None
    for attempt in range(_STARTUP_RETRY_COUNT):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt == _STARTUP_RETRY_COUNT - 1:
                break
            time.sleep(_STARTUP_RETRY_DELAY_SECONDS)
    raise last_error


def _configure_store(
    url: str | None = None,
    common_collection: str | None = None,
    scoped_collection: str | None = None,
    timeout: int | None = None,
):
    global QDRANT_URL, QDRANT_COMMON_COLLECTION, QDRANT_SCOPED_COLLECTION, COLLECTION_BY_TYPE, _timeout
    if url is not None:
        QDRANT_URL = url
    _timeout = timeout
    if common_collection is not None:
        QDRANT_COMMON_COLLECTION = common_collection
    if scoped_collection is not None:
        QDRANT_SCOPED_COLLECTION = scoped_collection
    COLLECTION_BY_TYPE = {
        "common": QDRANT_COMMON_COLLECTION,
        "scoped": QDRANT_SCOPED_COLLECTION,
    }


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
        _dense.start()
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
        _sparse.start()
    return _sparse


def _get_dense() -> Dense:
    if _dense is None:
        raise RuntimeError("search is not initialized")
    return _dense


def _get_langchain_dense():
    embeddings = _get_dense()
    unwrap = getattr(embeddings, "as_langchain_dense", None)
    if callable(unwrap):
        return unwrap()
    return embeddings


def _get_sparse() -> Sparse | None:
    return _sparse


def _sparse_uses_store(sparse: Sparse | None = None) -> bool:
    return isinstance(_get_sparse() if sparse is None else sparse, SparseEmbeddings)


def sparse_uses_store(sparse: Sparse | None = None) -> bool:
    return _sparse_uses_store(sparse)


def _get_dense_vector_size() -> int:
    if _dense_vector_size is None:
        raise RuntimeError("search is not initialized")
    return _dense_vector_size


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=os.getenv("QDRANT_URL", QDRANT_URL), timeout=_timeout)
    return _client


def ensure_collections():
    client = get_qdrant_client()
    dense_size = _get_dense_vector_size()
    for collection_name in COLLECTION_BY_TYPE.values():
        if client.collection_exists(collection_name):
            _ensure_sparse_vector(client, collection_name)
            continue
        sparse_vectors_config = (
            {"sparse": models.SparseVectorParams()}
            if _sparse_uses_store()
            else None
        )
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
            },
            sparse_vectors_config=sparse_vectors_config,
        )
    ensure_payload_indexes()


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
    for field_name in ("metadata.namespace", "metadata.filename"):
        _ensure_payload_index(client, QDRANT_COMMON_COLLECTION, field_name)
    for field_name in ("metadata.namespace", "metadata.scope_id", "metadata.filename"):
        _ensure_payload_index(client, QDRANT_SCOPED_COLLECTION, field_name)


def _ensure_payload_index(client: QdrantClient, collection_name: str, field_name: str):
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except Exception:
        pass


def _store_for(collection_type: CollectionType, mode: SearchMode) -> QdrantVectorStore:
    _require_search_ready()
    key = (collection_type, mode)
    if key not in _stores:
        raise RuntimeError("store is not initialized")
    return _stores[key]


def _get_store_unchecked(collection_type: CollectionType, mode: SearchMode) -> QdrantVectorStore:
    key = (collection_type, mode)
    if key not in _stores:
        retrieval_mode = _retrieval_mode(mode)
        _stores[key] = QdrantVectorStore(
            client=get_qdrant_client(),
            collection_name=COLLECTION_BY_TYPE[collection_type],
            embedding=_get_langchain_dense(),
            retrieval_mode=retrieval_mode,
            vector_name="dense",
            sparse_embedding=_get_sparse() if retrieval_mode in (RetrievalMode.SPARSE, RetrievalMode.HYBRID) else None,
            sparse_vector_name="sparse",
        )
    return _stores[key]


def _retrieval_mode(mode: SearchMode) -> RetrievalMode:
    if _sparse_uses_store():
        return {
            "dense": RetrievalMode.DENSE,
            "sparse": RetrievalMode.SPARSE,
            "hybrid": RetrievalMode.HYBRID,
        }[mode]
    return RETRIEVAL_MODE_BY_SEARCH_MODE[mode]


def _common_store(mode: SearchMode = "hybrid") -> QdrantVectorStore:
    return _store_for("common", mode)


def _scoped_store(mode: SearchMode = "hybrid") -> QdrantVectorStore:
    return _store_for("scoped", mode)


def search_dense(collection_type: CollectionType, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
    return _search_with_store(collection_type, "dense", query, limit, metadata_filter)


def search_sparse(collection_type: CollectionType, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
    return _search_with_store(collection_type, "sparse", query, limit, metadata_filter)


def search_hybrid(collection_type: CollectionType, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
    return _search_with_store(collection_type, "hybrid", query, limit, metadata_filter)


def _search_with_store(collection_type: CollectionType, mode: SearchMode, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
    docs = _store_for(collection_type, mode).similarity_search_with_score(query, k=limit, filter=metadata_filter)
    return _documents_with_scores_to_items(docs, collection_type)


def add_common_documents(chunks: list[dict], namespace: str = "default") -> int:
    if not chunks:
        return 0
    _require_search_ready()
    filename = _filename_from_chunks(chunks)
    with _document_lock("common", namespace, None, filename):
        delete_common_document(filename, namespace)
        _common_store(_write_mode()).add_documents(
            _to_documents(chunks, namespace),
            ids=[_point_id(chunk["id"]) for chunk in chunks],
        )
    return len(chunks)


def add_scoped_documents(chunks: list[dict], namespace: str = "default", scope_id: str | None = None) -> int:
    if not scope_id:
        raise ValueError("scope_id is required for scoped documents")
    if not chunks:
        return 0
    _require_search_ready()
    filename = _filename_from_chunks(chunks)
    with _document_lock("scoped", namespace, scope_id, filename):
        delete_scoped_document(filename, namespace, scope_id)
        _scoped_store(_write_mode()).add_documents(
            _to_documents(chunks, namespace, scope_id),
            ids=[_point_id(chunk["id"]) for chunk in chunks],
        )
    return len(chunks)


def delete_common_document(filename: str, namespace: str = "default") -> int:
    return _delete_by_filter(
        "common",
        _payload_filter(namespace=namespace, filename=filename),
    )


def delete_scoped_document(filename: str, namespace: str = "default", scope_id: str | None = None) -> int:
    return _delete_by_filter(
        "scoped",
        _payload_filter(namespace=namespace, scope_ids=[scope_id] if scope_id else None, filename=filename),
    )


def list_common_documents(namespace: str = "default") -> list[dict]:
    return _list_documents("common", _payload_filter(namespace=namespace))


def list_scoped_documents(namespace: str = "default", scope_ids: list[str] | None = None) -> list[dict]:
    return _list_documents("scoped", _payload_filter(namespace=namespace, scope_ids=scope_ids))


def list_documents(
    collection_type: Literal["all", "common", "scoped"] = "all",
    namespace: str = "default",
    scope_ids: list[str] | None = None,
) -> list[dict]:
    if collection_type == "common":
        return list_common_documents(namespace)
    if collection_type == "scoped":
        return list_scoped_documents(namespace, scope_ids)
    return list_common_documents(namespace) + list_scoped_documents(namespace, scope_ids)


def get_total_chunks(namespace: str = "default", scope_ids: list[str] | None = None) -> int:
    total = _count_documents("common", _payload_filter(namespace=namespace))
    if scope_ids:
        total += _count_documents("scoped", _payload_filter(namespace=namespace, scope_ids=scope_ids))
    return total


def get_search_documents(collection_type: CollectionType, metadata_filter: models.Filter) -> list[dict]:
    client = get_qdrant_client()
    collection_name = COLLECTION_BY_TYPE[collection_type]
    documents = []
    offset = None
    while True:
        rows, offset = client.scroll(
            collection_name=collection_name,
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
            source_id = metadata.get("source_id") or metadata.get("id") or str(row.id)
            documents.append({
                "id": source_id,
                "content": content,
                "metadata": metadata,
                "collection_type": collection_type,
            })
        if offset is None:
            break
    return documents


def build_common_filter(namespace: str) -> models.Filter:
    return _payload_filter(namespace=namespace)


def build_scoped_filter(namespace: str, scope_ids: list[str]) -> models.Filter:
    return _payload_filter(namespace=namespace, scope_ids=scope_ids)


def _to_documents(chunks: list[dict], namespace: str, scope_id: str | None = None) -> list[Document]:
    created_at = datetime.now(timezone.utc).isoformat()
    documents = []
    for chunk in chunks:
        metadata = dict(chunk.get("metadata") or {})
        metadata["source_id"] = chunk.get("id")
        metadata["namespace"] = namespace
        metadata["created_at"] = metadata.get("created_at") or created_at
        if scope_id is not None:
            metadata["scope_id"] = scope_id
        documents.append(Document(page_content=chunk["content"], metadata=metadata, id=chunk.get("id")))
    return documents


def _write_mode() -> SearchMode:
    return "hybrid" if _sparse_uses_store() else "dense"


def _filename_from_chunks(chunks: list[dict]) -> str:
    filename = chunks[0].get("metadata", {}).get("filename")
    if not filename:
        raise ValueError("chunk metadata.filename is required")
    return filename


def _payload_filter(
    namespace: str,
    scope_ids: list[str | None] | None = None,
    filename: str | None = None,
) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="metadata.namespace", match=models.MatchValue(value=namespace)),
    ]
    cleaned_scope_ids = [scope_id for scope_id in scope_ids or [] if scope_id]
    if cleaned_scope_ids:
        must.append(models.FieldCondition(key="metadata.scope_id", match=models.MatchAny(any=cleaned_scope_ids)))
    if filename:
        must.append(models.FieldCondition(key="metadata.filename", match=models.MatchValue(value=filename)))
    return models.Filter(must=must)


def _delete_by_filter(collection_type: CollectionType, metadata_filter: models.Filter) -> int:
    client = get_qdrant_client()
    collection_name = COLLECTION_BY_TYPE[collection_type]
    before = _count_documents(collection_type, metadata_filter)
    if before:
        client.delete(collection_name=collection_name, points_selector=models.FilterSelector(filter=metadata_filter))
    return before


def _list_documents(collection_type: CollectionType, metadata_filter: models.Filter) -> list[dict]:
    client = get_qdrant_client()
    collection_name = COLLECTION_BY_TYPE[collection_type]
    rows, _ = client.scroll(collection_name=collection_name, scroll_filter=metadata_filter, limit=10000, with_payload=True)
    seen: dict[tuple[str, str | None], dict] = {}
    for row in rows:
        metadata = _metadata_from_payload(row.payload)
        filename = metadata.get("filename")
        if not filename:
            continue
        key = (filename, metadata.get("scope_id"))
        if key not in seen:
            seen[key] = {
                "filename": filename,
                "chunks": 0,
                "created_at": metadata.get("created_at", ""),
                "collection_type": collection_type,
                "namespace": metadata.get("namespace", ""),
                "scope_id": metadata.get("scope_id"),
            }
        seen[key]["chunks"] += 1
    return list(seen.values())


def _count_documents(collection_type: CollectionType, metadata_filter: models.Filter) -> int:
    client = get_qdrant_client()
    result = client.count(collection_name=COLLECTION_BY_TYPE[collection_type], count_filter=metadata_filter, exact=True)
    return int(result.count)


def _documents_with_scores_to_items(docs, collection_type: CollectionType) -> list[dict]:
    items = []
    for doc, score in docs:
        metadata = dict(doc.metadata or {})
        items.append({
            "id": doc.id or metadata.get("source_id") or metadata.get("id", ""),
            "content": doc.page_content,
            "metadata": metadata,
            "collection_type": collection_type,
            "_score": float(score),
        })
    return items


def _metadata_from_payload(payload: dict | None) -> dict:
    if not payload:
        return {}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return payload


def _document_lock(collection_type: CollectionType, namespace: str, scope_id: str | None, filename: str):
    key = _document_key(collection_type, namespace, scope_id, filename)
    with _document_locks_guard:
        return _document_locks[key]


def _document_key(collection_type: CollectionType, namespace: str, scope_id: str | None, filename: str) -> str:
    return f"{collection_type}:{namespace}:{scope_id or ''}:{filename}"


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
