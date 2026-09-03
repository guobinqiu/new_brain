"""Chroma-backed document storage through LangChain Chroma."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Literal

from chromadb.utils.embedding_functions import SparseEmbeddingFunction

from rag.config import SEARCH_CONFIG
from rag.dense.base import Dense
from rag.dense.huggingface import HuggingFaceDense
from rag.scope import app_collection, collection_name_for_app, current_collection
from rag.sparse.base import Sparse


SearchMode = Literal["dense", "sparse", "hybrid"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPARSE_VECTOR_KEY = "sparse_embedding"


class ChromaStore:
    backend_name = "chroma"

    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        persist_dir: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.persist_dir = persist_dir
        self.client = None
        self._ready = False

    def start(self) -> None:
        if not self.dense.ready:
            raise RuntimeError("dense is not initialized")
        if self.sparse is not None and not self.sparse.ready:
            raise RuntimeError("sparse is not initialized")
        self._ready = True

    def stop(self) -> None:
        self.client = None
        self._ready = False

    def drop_collections(self) -> None:
        collection_name = self._chunks_collection()
        try:
            self._client().delete_collection(collection_name)
        except Exception:
            pass

    @property
    def ready(self) -> bool:
        return self._ready

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        if not chunks:
            return 0
        if not file_id:
            raise ValueError("file_id is required")
        self._require_ready()
        self.delete_file_chunks(file_id)
        self._collection().add(
            ids=[_point_id(chunk["id"]) for chunk in chunks],
            documents=[chunk["content"] for chunk in chunks],
            metadatas=[_metadata_for_chunk(chunk, file_id) for chunk in chunks],
            embeddings=self.dense.embed_documents([chunk["content"] for chunk in chunks]),
        )
        return len(chunks)

    def delete_file_chunks(self, file_id: str) -> int:
        return self._delete_by_filter(_file_payload_filter([file_id]))

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        return len(self.get_search_documents(self.build_file_filter(file_ids)))

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        rows = self._collection_get(self.build_file_filter(file_ids))
        documents = sorted(_rows_to_documents(rows), key=_chunk_sort_key)
        start = _chunk_cursor_position(documents, cursor)
        page_rows = documents[start:start + limit]
        return {
            "documents": page_rows,
            "next_cursor": _encode_chunk_cursor(page_rows[-1]) if start + limit < len(documents) and page_rows else None,
            "has_more": start + limit < len(documents),
        }

    def get_dense_vector(self, chunk_id: str) -> list[float] | None:
        rows = self._collection().get(ids=[chunk_id], include=["embeddings"])
        embeddings = rows.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return None
        vector = embeddings[0]
        return vector.tolist() if hasattr(vector, "tolist") else list(vector)

    def get_sparse_vector(self, chunk_id: str) -> dict | None:
        raise NotImplementedError("sparse vector is not supported by current store")

    def supports_dense_vector(self) -> bool:
        return True

    def supports_sparse_vector(self, sparse: Sparse | None = None) -> bool:
        return self.sparse_uses_store(sparse)

    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        with app_collection(app_id):
            self._ensure_collection()
        return collection_name

    def app_collection_exists(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        names = [getattr(collection, "name", collection) for collection in self._client().list_collections()]
        return collection_name in names

    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        if not self.app_collection_exists(app_id):
            return False
        self._client().delete_collection(collection_name)
        return True

    def app_context(self, app_id: str):
        return app_collection(app_id)

    def get_search_documents(self, metadata_filter: dict | None) -> list[dict]:
        rows = self._collection_get(metadata_filter)
        return _rows_to_documents(rows)

    def build_file_filter(self, file_ids: list[str] | None = None) -> dict | None:
        if file_ids is None:
            return None
        if not file_ids:
            raise ValueError("file_ids cannot be empty")
        return _file_payload_filter(file_ids)

    def encode_dense_query(self, query: str):
        return self.dense.embed_query(query)

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: dict | None) -> list[dict]:
        rows = self._collection().query(
            query_embeddings=[query_vector],
            n_results=limit,
            where=metadata_filter,
            include=["documents", "metadatas", "distances"],
        )
        return _query_rows_to_items(rows)

    def search_dense(self, query: str, limit: int, metadata_filter: dict | None) -> list[dict]:
        return self.query_dense_vector(self.encode_dense_query(query), limit, metadata_filter)

    def encode_sparse_query(self, query: str):
        return query

    def query_sparse_vector(self, query_vector, limit: int, metadata_filter: dict | None) -> list[dict]:
        docs = self._search_sparse_or_hybrid("sparse", query_vector, limit, metadata_filter)
        return _documents_with_scores_to_items(docs)

    def search_sparse(self, query: str, limit: int, metadata_filter: dict | None) -> list[dict]:
        return self.query_sparse_vector(self.encode_sparse_query(query), limit, metadata_filter)

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: dict | None,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        docs = self._search_sparse_or_hybrid("hybrid", query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k)
        return _documents_with_scores_to_items(docs)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        candidate = self.sparse if sparse is None else sparse
        return isinstance(candidate, SparseEmbeddingFunction)

    def _client(self):
        if self.client is None:
            import chromadb

            self.client = chromadb.PersistentClient(path=_persist_path(self.persist_dir))
        return self.client

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("search is not initialized")

    def _ensure_collection(self) -> None:
        collection_name = self._chunks_collection()
        if self.sparse_uses_store():
            try:
                self._client().get_or_create_collection(
                    name=collection_name,
                    schema=self._chroma_schema(),
                    embedding_function=None,
                )
            except Exception as exc:
                if "Sparse vector indexing is not enabled in local" in str(exc):
                    raise RuntimeError(
                        "本地 Chroma 不支持 vector sparse。Chroma 本地配置请使用 sparse.type=bm25。"
                    ) from exc
                raise
            return
        self._client().get_or_create_collection(name=collection_name, embedding_function=None)

    def _chroma_schema(self):
        from chromadb import K, Schema, SparseVectorIndexConfig

        return Schema().create_index(
            SparseVectorIndexConfig(
                embedding_function=self.sparse,
                source_key=K.DOCUMENT,
            ),
            key=SPARSE_VECTOR_KEY,
        )

    def _search_sparse_or_hybrid(
        self,
        mode: SearchMode,
        query: str,
        limit: int,
        metadata_filter: dict,
        dense_weight: float | None = None,
        sparse_weight: float | None = None,
        rrf_k: int | None = None,
    ):
        from chromadb import K, Knn, Rrf, Search

        if mode == "sparse":
            rank = Knn(query=query, key=SPARSE_VECTOR_KEY, limit=limit)
        else:
            rank = Rrf(
                ranks=[
                    Knn(query=self.dense.embed_query(query), limit=limit, return_rank=True),
                    Knn(query=query, key=SPARSE_VECTOR_KEY, limit=limit, return_rank=True),
                ],
                weights=[
                    float(dense_weight if dense_weight is not None else _search_config_value("dense_weight", 0.5)),
                    float(sparse_weight if sparse_weight is not None else _search_config_value("sparse_weight", 0.5)),
                ],
                k=int(rrf_k if rrf_k is not None else _search_config_value("rrf_k", 60)),
            )
        search = Search(where=metadata_filter, rank=rank, limit=limit, select=[K.DOCUMENT, K.SCORE, "metadata"])
        rows = self._collection().search(search).rows()
        records = rows[0] if rows else []
        results = []
        for rank_index, record in enumerate(records):
            if record["document"] is None:
                continue
            results.append({
                "id": record["id"],
                "content": record["document"],
                "metadata": record["metadata"] or {},
                "_score": 1.0 / (rank_index + 1),
            })
        return results

    def _delete_by_filter(self, metadata_filter: dict) -> int:
        before = len((self._collection_get(metadata_filter).get("ids") or []))
        if before:
            self._collection().delete(where=metadata_filter)
        return before

    def _collection_get(self, metadata_filter: dict | None) -> dict:
        if metadata_filter is None:
            return self._collection().get(include=["documents", "metadatas"])
        return self._collection().get(where=metadata_filter, include=["documents", "metadatas"])

    def _collection(self):
        return self._client().get_collection(self._chunks_collection())

    def _chunks_collection(self) -> str:
        return current_collection()


def _persist_path(persist_dir: str | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if persist_dir is None:
        return None
    path = Path(persist_dir).expanduser()
    if not path.is_absolute():
        path = project_root / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _distance_to_score(distance: float) -> float:
    return 1.0 / (1.0 + float(distance))


def _search_config_value(key: str, default):
    return SEARCH_CONFIG.get(key, default)


def _documents_with_scores_to_items(docs: list[dict]) -> list[dict]:
    return docs


def _rows_to_documents(rows: dict) -> list[dict]:
    documents = rows.get("documents") or []
    metadatas = rows.get("metadatas") or []
    ids = rows.get("ids") or []
    results = []
    for row_id, content, metadata in zip(ids, documents, metadatas):
        metadata = dict(metadata or {})
        results.append({
            "id": row_id,
            "content": content or "",
            "metadata": metadata,
        })
    return results


def _chunk_sort_key(document: dict) -> tuple[str, int, str]:
    metadata = document["metadata"]
    return (str(metadata["file_id"]), int(metadata["chunk_index"]), str(document["id"]))


def _chunk_cursor_position(documents: list[dict], cursor: str | None) -> int:
    if not cursor:
        return 0
    cursor_key = _decode_chunk_cursor(cursor)
    for index, document in enumerate(documents):
        if _chunk_sort_key(document) > cursor_key:
            return index
    return len(documents)


def _encode_chunk_cursor(document: dict) -> str:
    metadata = document["metadata"]
    data = {
        "file_id": str(metadata["file_id"]),
        "chunk_index": int(metadata["chunk_index"]),
        "chunk_id": str(document["id"]),
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_chunk_cursor(cursor: str) -> tuple[str, int, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(data, dict) or not {"file_id", "chunk_index", "chunk_id"} <= data.keys():
        raise ValueError("invalid cursor")
    return (str(data["file_id"]), int(data["chunk_index"]), str(data["chunk_id"]))


def _metadata_for_chunk(chunk: dict, file_id: str) -> dict:
    metadata = dict(chunk.get("metadata") or {})
    metadata["file_id"] = file_id
    if "chunk_index" not in metadata:
        raise ValueError("chunk metadata.chunk_index is required")
    if not metadata.get("filename"):
        raise ValueError("chunk metadata.filename is required")
    return metadata


def _file_payload_filter(file_ids: list[str]) -> dict:
    return {"file_id": {"$in": file_ids}}


def _query_rows_to_items(rows: dict) -> list[dict]:
    items = []
    ids = (rows.get("ids") or [[]])[0]
    documents = (rows.get("documents") or [[]])[0]
    metadatas = (rows.get("metadatas") or [[]])[0]
    distances = (rows.get("distances") or [[]])[0]
    for row_id, content, metadata, distance in zip(ids, documents, metadatas, distances):
        items.append({
            "id": row_id,
            "content": content or "",
            "metadata": dict(metadata or {}),
            "_score": _distance_to_score(distance),
        })
    return items


def _point_id(chunk_id: str) -> str:
    return chunk_id
