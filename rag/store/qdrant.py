"""Qdrant-backed document storage and collection management."""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag.config import QDRANT_URL
from rag.dense.base import Dense
from rag.dense.huggingface import HuggingFaceDense
from rag.scope import app_collection, collection_name_for_app, current_app_id, current_collection
from rag.sparse.base import Sparse
from rag.store.startup import run_with_startup_retry


SearchMode = Literal["dense", "sparse", "hybrid"]

_document_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_document_locks_guard = threading.Lock()
logger = logging.getLogger("rag.indexing")


class QdrantStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        url: str | None = None,
        timeout: int | None = None,
        parallel_sparse_embedding: bool = False,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.url = url or QDRANT_URL
        self.timeout = timeout
        self.parallel_sparse_embedding = parallel_sparse_embedding
        self.client: QdrantClient | None = None
        self.dense_vector_size: int | None = None
        self._ready = False

    def start(self) -> None:
        """启动阶段完成存储运行时初始化；请求阶段不做懒初始化。"""
        if not self.dense.ready:
            raise RuntimeError("dense is not initialized")
        if self.sparse is not None and not self.sparse.ready:
            raise RuntimeError("sparse is not initialized")
        self.dense_vector_size = len(self.dense.embed_query("dimension probe"))
        self._ready = True

    def stop(self) -> None:
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if callable(close):
                close()
        self.client = None
        self._ready = False

    def drop_collections(self) -> None:
        collection_name = self._chunks_collection()
        client = self._client()
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name)

    @property
    def ready(self) -> bool:
        return self._ready

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        if not chunks:
            return 0
        if not file_id:
            raise ValueError("file_id is required")
        self._require_ready()
        with _document_lock(file_id):
            app_id = current_app_id()
            self.delete_file_chunks(file_id)
            points = self._to_points(chunks, file_id)
            started = time.perf_counter()
            logger.info("Qdrant upsert start", extra={"event": "qdrant_upsert_start", "stage": "index", "backend": "qdrant", "retriever": "vector", "app_id": app_id, "file_id": file_id, "chunk_count": len(chunks), "point_count": len(points)})
            self._client().upsert(
                collection_name=self._chunks_collection(),
                points=points,
            )
            total_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info("Qdrant upsert done", extra={"event": "qdrant_upsert_done", "stage": "index", "backend": "qdrant", "retriever": "vector", "app_id": app_id, "file_id": file_id, "chunk_count": len(chunks), "point_count": len(points), "total_ms": total_ms, "status": "ok"})
        return len(chunks)

    def delete_file_chunks(self, file_id: str) -> int:
        return self._delete_by_filter(_file_payload_filter(file_ids=[file_id]))

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        return self._count_documents(self.build_file_filter(file_ids))

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        scroll_filter = _combine_chunk_filters(self.build_file_filter(file_ids), _chunk_cursor_filter(cursor))
        try:
            rows, _ = self._client().scroll(
                collection_name=self._chunks_collection(),
                scroll_filter=scroll_filter,
                limit=limit + 1,
                order_by="metadata.chunk_index",
                offset=None,
                with_payload=True,
                with_vectors=False,
            )
        except UnexpectedResponse as exc:
            if _is_collection_not_found(exc):
                return {"documents": [], "next_cursor": None, "has_more": False}
            raise
        page_rows = rows[:limit]
        return {
            "documents": [_record_to_document(row) for row in page_rows],
            "next_cursor": _encode_chunk_cursor(page_rows[-1]) if len(rows) > limit and page_rows else None,
            "has_more": len(rows) > limit,
        }

    def get_dense_vector(self, chunk_id: str) -> list[float] | None:
        vectors = self._get_point_vectors(chunk_id)
        if vectors is None:
            return None
        dense = vectors.get("dense") if isinstance(vectors, dict) else vectors
        return list(dense) if dense is not None else None

    def get_sparse_vector(self, chunk_id: str) -> dict | None:
        vectors = self._get_point_vectors(chunk_id)
        if not isinstance(vectors, dict):
            return None
        sparse = vectors.get("sparse")
        if sparse is None:
            return None
        indices = getattr(sparse, "indices", None)
        values = getattr(sparse, "values", None)
        if indices is None and isinstance(sparse, dict):
            indices = sparse.get("indices")
            values = sparse.get("values")
        return {"indices": list(indices or []), "values": list(values or [])}

    def supports_dense_vector(self) -> bool:
        return True

    def supports_sparse_vector(self, sparse: Sparse | None = None) -> bool:
        return self.sparse_uses_store(sparse)

    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        run_with_startup_retry(lambda: self.ensure_collections(collection_name))
        return collection_name

    def app_collection_exists(self, app_id: str) -> bool:
        return self._client().collection_exists(collection_name_for_app(app_id))

    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        client = self._client()
        if not client.collection_exists(collection_name):
            return False
        client.delete_collection(collection_name)
        return True

    def app_context(self, app_id: str):
        return app_collection(app_id)

    def get_search_documents(self, metadata_filter: models.Filter | None) -> list[dict]:
        documents = []
        offset = None
        while True:
            try:
                rows, offset = self._client().scroll(
                    collection_name=self._chunks_collection(),
                    scroll_filter=metadata_filter,
                    limit=1000,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
            except UnexpectedResponse as exc:
                if _is_collection_not_found(exc):
                    return []
                raise
            documents.extend(_record_to_document(row) for row in rows)
            if offset is None:
                break
        return documents

    def build_file_filter(self, file_ids: list[str] | None = None) -> models.Filter | None:
        if file_ids is None:
            return None
        if not file_ids:
            raise ValueError("file_ids cannot be empty")
        return _file_payload_filter(file_ids=file_ids)

    def encode_dense_query(self, query: str):
        return self.dense.embed_query(query)

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return self._query_points(query_vector, "dense", limit, metadata_filter)

    def search_dense(self, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return self.query_dense_vector(self.encode_dense_query(query), limit, metadata_filter)

    def encode_sparse_query(self, query: str):
        if self.sparse is None:
            raise RuntimeError("sparse is not initialized")
        return _qdrant_sparse_vector(self.sparse.embed_query(query))

    def query_sparse_vector(self, query_vector, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return self._query_points(query_vector, "sparse", limit, metadata_filter)

    def search_sparse(self, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return self.query_sparse_vector(self.encode_sparse_query(query), limit, metadata_filter)

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: models.Filter,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        dense_items = self.search_dense(query, limit, metadata_filter)
        sparse_items = self.search_sparse(query, limit, metadata_filter)
        return _weighted_reciprocal_rank(dense_items, sparse_items, limit, dense_weight, sparse_weight, rrf_k)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        from rag.sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

        return isinstance(self.sparse if sparse is None else sparse, QdrantBGEM3Sparse)

    def ensure_collections(self, collection_name: str | None = None) -> None:
        client = self._client()
        dense_size = self._get_dense_vector_size()
        target_collection = collection_name or self._chunks_collection()
        if client.collection_exists(target_collection):
            self._ensure_sparse_vector(target_collection)
            self.ensure_payload_indexes(target_collection)
            return
        sparse_vectors_config = (
            {"sparse": models.SparseVectorParams()}
            if self.sparse_uses_store()
            else None
        )
        client.create_collection(
            collection_name=target_collection,
            vectors_config={
                "dense": models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
            },
            sparse_vectors_config=sparse_vectors_config,
        )
        _wait_collection_ready(client, target_collection)
        self.ensure_payload_indexes(target_collection)

    def ensure_payload_indexes(self, collection_name: str | None = None) -> None:
        client = self._client()
        target_collection = collection_name or self._chunks_collection()
        _ensure_payload_index(client, target_collection, "metadata.file_id", models.PayloadSchemaType.KEYWORD)
        _ensure_payload_index(client, target_collection, "metadata.chunk_index", models.PayloadSchemaType.INTEGER)

    def _client(self) -> QdrantClient:
        if self.client is None:
            self.client = QdrantClient(url=self.url, timeout=self.timeout, check_compatibility=False)
        return self.client

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("search is not initialized")

    def _get_dense_vector_size(self) -> int:
        if self.dense_vector_size is None:
            raise RuntimeError("search is not initialized")
        return self.dense_vector_size

    def _chunks_collection(self) -> str:
        return current_collection()

    def _ensure_sparse_vector(self, collection_name: str) -> None:
        if not self.sparse_uses_store():
            return
        collection = self._client().get_collection(collection_name)
        sparse_vectors = collection.config.params.sparse_vectors or {}
        if "sparse" in sparse_vectors:
            return
        self._client().update_collection(
            collection_name=collection_name,
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )

    def _query_points(self, query, vector_name: str, limit: int, metadata_filter: models.Filter | None) -> list[dict]:
        self._require_ready()
        try:
            response = self._client().query_points(
                collection_name=self._chunks_collection(),
                query=query,
                using=vector_name,
                query_filter=metadata_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        except UnexpectedResponse as exc:
            if _is_collection_not_found(exc):
                return []
            raise
        return [_point_to_item(point) for point in response.points]

    def _get_point_vectors(self, chunk_id: str):
        self._require_ready()
        rows = self._client().retrieve(
            collection_name=self._chunks_collection(),
            ids=[_point_id(chunk_id)],
            with_payload=False,
            with_vectors=True,
        )
        if not rows:
            return None
        return getattr(rows[0], "vector", None)

    def _delete_by_filter(self, metadata_filter: models.Filter) -> int:
        before = self._count_documents(metadata_filter)
        if before:
            try:
                self._client().delete(collection_name=self._chunks_collection(), points_selector=models.FilterSelector(filter=metadata_filter))
            except UnexpectedResponse as exc:
                if _is_collection_not_found(exc):
                    return 0
                raise
        return before

    def _count_documents(self, metadata_filter: models.Filter | None) -> int:
        try:
            result = self._client().count(collection_name=self._chunks_collection(), count_filter=metadata_filter, exact=True)
        except UnexpectedResponse as exc:
            if _is_collection_not_found(exc):
                return 0
            raise
        return int(result.count)

    def _to_points(self, chunks: list[dict], file_id: str) -> list[models.PointStruct]:
        app_id = current_app_id()
        contents = [chunk["content"] for chunk in chunks]
        if self.sparse_uses_store() and self.parallel_sparse_embedding:
            with ThreadPoolExecutor(max_workers=2) as executor:
                dense_future = executor.submit(self._dense_vectors_for_documents, contents, file_id, app_id)
                sparse_future = executor.submit(self._logged_sparse_vectors_for_documents, contents, file_id, app_id)
                dense_vectors = dense_future.result()
                sparse_vectors = sparse_future.result()
        else:
            dense_vectors = self._dense_vectors_for_documents(contents, file_id, app_id)
            sparse_vectors = self._logged_sparse_vectors_for_documents(contents, file_id, app_id) if self.sparse_uses_store() else [None] * len(chunks)
        points = []
        for chunk, dense_vector, sparse_vector in zip(chunks, dense_vectors, sparse_vectors):
            point_id = _point_id(chunk["id"])
            vector = {"dense": dense_vector}
            if sparse_vector is not None:
                vector["sparse"] = sparse_vector
            points.append(models.PointStruct(id=point_id, vector=vector, payload=_payload_for_chunk(chunk, file_id)))
        return points

    def _dense_vectors_for_documents(self, contents: list[str], file_id: str, app_id: str) -> list[list[float]]:
        started = time.perf_counter()
        logger.info("Dense embedding start", extra={"event": "dense_embedding_start", "stage": "embedding", "backend": "model", "retriever": "dense", "app_id": app_id, "file_id": file_id, "chunk_count": len(contents)})
        dense_vectors = self.dense.embed_documents(contents)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Dense embedding done", extra={"event": "dense_embedding_done", "stage": "embedding", "backend": "model", "retriever": "dense", "app_id": app_id, "file_id": file_id, "chunk_count": len(contents), "total_ms": total_ms, "status": "ok"})
        return dense_vectors

    def _logged_sparse_vectors_for_documents(self, contents: list[str], file_id: str, app_id: str) -> list[models.SparseVector]:
        started = time.perf_counter()
        logger.info("Sparse embedding start", extra={"event": "sparse_embedding_start", "stage": "embedding", "backend": "model", "retriever": "sparse_vector", "app_id": app_id, "file_id": file_id, "chunk_count": len(contents)})
        sparse_vectors = self._sparse_vectors_for_documents(contents)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Sparse embedding done", extra={"event": "sparse_embedding_done", "stage": "embedding", "backend": "model", "retriever": "sparse_vector", "app_id": app_id, "file_id": file_id, "chunk_count": len(contents), "total_ms": total_ms, "status": "ok"})
        return sparse_vectors

    def _sparse_vectors_for_documents(self, texts: list[str]) -> list[models.SparseVector]:
        if self.sparse is None:
            raise RuntimeError("sparse is not initialized")
        return [_qdrant_sparse_vector(vector) for vector in self.sparse.embed_documents(texts)]


def _wait_collection_ready(client: QdrantClient, collection_name: str) -> None:
    deadline = time.monotonic() + 5
    last_error = None
    while time.monotonic() < deadline:
        try:
            client.get_collection(collection_name)
            client.count(collection_name=collection_name, exact=True)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


def _ensure_payload_index(client: QdrantClient, collection_name: str, field_name: str, field_schema: models.PayloadSchemaType):
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
        )
    except Exception:
        pass


def _qdrant_sparse_vector(vector) -> models.SparseVector:
    return models.SparseVector(indices=list(vector.indices), values=list(vector.values))


def _file_payload_filter(file_ids: list[str]) -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="metadata.file_id", match=models.MatchAny(any=file_ids)),
    ])


def _chunk_cursor_filter(cursor: str | None) -> models.Filter | None:
    if not cursor:
        return None
    data = _decode_chunk_cursor(cursor)
    return models.Filter(must=[
        models.FieldCondition(key="metadata.chunk_index", range=models.Range(gt=int(data["chunk_index"]))),
    ])


def _combine_chunk_filters(*filters: models.Filter | None) -> models.Filter | None:
    active = [metadata_filter for metadata_filter in filters if metadata_filter is not None]
    if not active:
        return None
    must = []
    for metadata_filter in active:
        must.extend(metadata_filter.must or [])
    return models.Filter(must=must)


def _encode_chunk_cursor(row) -> str:
    payload = row.payload or {}
    metadata = _metadata_from_payload(payload)
    data = {
        "file_id": str(metadata["file_id"]),
        "chunk_index": int(metadata["chunk_index"]),
        "chunk_id": str(row.id),
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_chunk_cursor(cursor: str) -> dict:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(data, dict) or not {"file_id", "chunk_index", "chunk_id"} <= data.keys():
        raise ValueError("invalid cursor")
    return data


def _record_to_document(row) -> dict:
    payload = row.payload or {}
    metadata = _metadata_from_payload(payload)
    content = payload.get("page_content") or payload.get("content") or ""
    return {
        "id": str(row.id),
        "content": content,
        "metadata": metadata,
    }


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


def _is_collection_not_found(exc: UnexpectedResponse) -> bool:
    return getattr(exc, "status_code", None) == 404 or "Collection" in str(exc) and "doesn't exist" in str(exc)


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
    return chunk_id
