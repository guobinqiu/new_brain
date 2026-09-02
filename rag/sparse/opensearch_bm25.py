from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import httpx

from rag.scope import current_app_id


logger = logging.getLogger("rag.indexing")


class OpenSearchBM25Sparse:
    backend = "opensearch"
    retriever = "bm25"

    def __init__(self, url: str, index_prefix: str = "", timeout: int = 10, username: str | None = None, password: str | None = None):
        self.url = url.rstrip("/")
        self.index_prefix = index_prefix.strip("_")
        self.timeout = timeout
        self.username = username
        self.password = password
        self.ready = False

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def supports_search_index(self) -> bool:
        return True

    def supports_sparse_vector(self) -> bool:
        return False

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> None:
        if not self.ready:
            raise RuntimeError("sparse is not initialized")
        if not chunks:
            return
        app_id = current_app_id()
        started = time.perf_counter()
        logger.info(
            "OpenSearch bulk start",
            extra={
                "event": "opensearch_bulk_start",
                "stage": "index",
                "backend": self.backend,
                "retriever": "bm25",
                "app_id": app_id,
                "file_id": file_id,
                "chunk_count": len(chunks),
            },
        )
        lines = []
        for chunk in chunks:
            chunk_id = str(chunk["id"])
            lines.append({"index": {"_index": self._index_name(app_id), "_id": chunk_id}})
            lines.append({
                "chunk_id": chunk_id,
                "content": chunk.get("content", ""),
                "metadata": {**dict(chunk.get("metadata") or {}), "file_id": file_id},
            })
        response = httpx.post(
            f"{self.url}/_bulk?refresh=wait_for",
            content="\n".join(json.dumps(line, ensure_ascii=False, separators=(",", ":")) for line in lines) + "\n",
            headers={"Content-Type": "application/x-ndjson"},
            timeout=self.timeout,
            auth=self._auth(),
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            errors = _bulk_errors(body)
            logger.error(
                "OpenSearch bulk failed",
                extra={
                    "event": "opensearch_bulk_failed",
                    "stage": "index",
                    "backend": self.backend,
                    "retriever": "bm25",
                    "app_id": app_id,
                    "file_id": file_id,
                    "chunk_count": len(chunks),
                    "errors": errors,
                },
            )
            raise RuntimeError(f"opensearch bulk index failed: {errors[:3]}")
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "OpenSearch bulk done",
            extra={
                "event": "opensearch_bulk_done",
                "stage": "index",
                "backend": self.backend,
                "retriever": "bm25",
                "app_id": app_id,
                "file_id": file_id,
                "chunk_count": len(chunks),
                "total_ms": total_ms,
                "status": "ok",
            },
        )

    def delete_file_chunks(self, file_id: str) -> None:
        if not self.ready:
            raise RuntimeError("sparse is not initialized")
        app_id = current_app_id()
        response = httpx.post(
            f"{self.url}/{self._index_name(app_id)}/_delete_by_query",
            json={"query": {"term": {"metadata.file_id": file_id}}},
            timeout=self.timeout,
            auth=self._auth(),
        )
        if response.status_code == 404:
            return
        response.raise_for_status()

    def ensure_app_collection(self, app_id: str) -> str:
        self._ensure_index(app_id)
        return self._index_name(app_id)

    def app_collection_exists(self, app_id: str) -> bool:
        response = httpx.head(f"{self.url}/{self._index_name(app_id)}", timeout=self.timeout, auth=self._auth())
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def drop_app_collection(self, app_id: str) -> bool:
        response = httpx.delete(f"{self.url}/{self._index_name(app_id)}", timeout=self.timeout, auth=self._auth())
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        return self.search_index(query, limit)

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        if not self.ready:
            raise RuntimeError("sparse is not initialized")
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        app_id = current_app_id()
        body: dict[str, Any] = {
            "size": limit + 1,
            "query": {
                "bool": {
                    "filter": _file_filters(file_ids),
                },
            },
            "sort": [
                {"metadata.chunk_index": "asc"},
                {"chunk_id": "asc"},
            ],
        }
        if cursor:
            body["search_after"] = _decode_chunk_cursor(cursor)
        response = httpx.post(f"{self.url}/{self._index_name(app_id)}/_search", json=body, timeout=self.timeout, auth=self._auth())
        if response.status_code == 404:
            return {"documents": [], "next_cursor": None, "has_more": False}
        response.raise_for_status()
        rows = response.json().get("hits", {}).get("hits", [])
        page_rows = rows[:limit]
        return {
            "documents": [_hit_to_item(hit) for hit in page_rows],
            "next_cursor": _encode_chunk_cursor(page_rows[-1]) if len(rows) > limit and page_rows else None,
            "has_more": len(rows) > limit,
        }

    def search_index(self, query: str, limit: int, *, app_id: str | None = None, file_ids: list[str] | None = None) -> list[dict]:
        if not self.ready:
            raise RuntimeError("sparse is not initialized")
        app_id = app_id or current_app_id()
        body: dict[str, Any] = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": _file_filters(file_ids),
                },
            },
        }
        response = httpx.post(f"{self.url}/{self._index_name(app_id)}/_search", json=body, timeout=self.timeout, auth=self._auth())
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [_hit_to_item(hit) for hit in response.json().get("hits", {}).get("hits", [])]

    def _ensure_index(self, app_id: str) -> None:
        index_name = self._index_name(app_id)
        response = httpx.put(
            f"{self.url}/{index_name}",
            json={
                "mappings": self._mappings(),
            },
            timeout=self.timeout,
            auth=self._auth(),
        )
        if response.status_code == 400 and "resource_already_exists_exception" in response.text:
            return
        if response.status_code >= 400:
            logger.error(
                "OpenSearch ensure index failed",
                extra={
                    "event": "opensearch_ensure_index_failed",
                    "stage": "index",
                    "backend": self.backend,
                    "retriever": "bm25",
                    "app_id": app_id,
                    "index_name": index_name,
                    "status_code": response.status_code,
                    "error": response.text,
                },
            )
        response.raise_for_status()

    def _index_name(self, app_id: str) -> str:
        prefix = f"{self.index_prefix}_" if self.index_prefix else ""
        return f"{prefix}{app_id}_chunks"

    def _mappings(self) -> dict:
        return {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "content": {"type": "text", "analyzer": "standard"},
                "metadata": {
                    "properties": {
                        "file_id": {"type": "keyword"},
                        "filename": {"type": "keyword"},
                        "chunk_index": {"type": "integer"},
                        "s3_url": {"type": "keyword"},
                        "created_at": {"type": "date", "ignore_malformed": True},
                    },
                },
            },
        }

    def _auth(self) -> tuple[str, str] | None:
        if self.username is None:
            return None
        return (self.username, self.password or "")


def _file_filters(file_ids: list[str] | None) -> list[dict]:
    if file_ids:
        return [{"terms": {"metadata.file_id": list(file_ids)}}]
    return []


def _bulk_errors(body: dict) -> list[dict]:
    errors = []
    for item in body.get("items", []):
        if not isinstance(item, dict):
            continue
        result = item.get("index") or item.get("create") or item.get("update") or item.get("delete") or {}
        error = result.get("error")
        if error:
            errors.append({
                "id": result.get("_id"),
                "status": result.get("status"),
                "error": error,
            })
        if len(errors) >= 5:
            break
    return errors


def _encode_chunk_cursor(hit: dict) -> str:
    sort = hit.get("sort")
    if not isinstance(sort, list) or len(sort) < 2:
        raise ValueError("invalid opensearch sort cursor")
    raw = json.dumps(sort[:2], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_chunk_cursor(cursor: str) -> list[Any]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(data, list) or len(data) < 2:
        raise ValueError("invalid cursor")
    return data[:2]


def _hit_to_item(hit: dict) -> dict:
    source = hit.get("_source") or {}
    return {
        "id": source.get("chunk_id") or hit.get("_id"),
        "content": source.get("content", ""),
        "metadata": source.get("metadata") or {},
        "_score": float(hit.get("_score") or 0.0),
    }
