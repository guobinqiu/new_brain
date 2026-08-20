"""Chroma-backed document storage through LangChain Chroma."""
from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path
from typing import Literal
from chromadb.utils.embedding_functions import SparseEmbeddingFunction
from config import SEARCH_CONFIG
from collection_names import app_collection, collection_name_for_app, current_collection
from dense.base import Dense
from dense.huggingface import HuggingFaceDense
from sparse.base import Sparse


SearchMode = Literal["dense", "sparse", "hybrid"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_dense: Dense | None = None
_sparse: Sparse | None = None
_persist_dir: str | None = None
_stores: dict[SearchMode, object] = {}
_client = None
_ready = False
SPARSE_VECTOR_KEY = "sparse_embedding"


class ChromaStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        persist_dir: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.persist_dir = persist_dir

    def start(self) -> None:
        init_store(
            dense=self.dense,
            sparse=self.sparse,
            persist_dir=self.persist_dir,
        )

    def stop(self) -> None:
        close_store()

    def drop_collections(self) -> None:
        _configure_store(self.persist_dir)
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

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        return list_chunks(file_ids=file_ids, limit=limit, cursor=cursor)

    def ensure_app_collection(self, app_id: str) -> str:
        _configure_store(self.persist_dir)
        return ensure_app_collection(app_id)

    def app_collection_exists(self, app_id: str) -> bool:
        _configure_store(self.persist_dir)
        return app_collection_exists(app_id)

    def drop_app_collection(self, app_id: str) -> bool:
        _configure_store(self.persist_dir)
        return drop_app_collection(app_id)

    def app_context(self, app_id: str):
        return app_collection(app_id)

    def get_search_documents(self, metadata_filter: dict | None) -> list[dict]:
        return get_search_documents(metadata_filter)

    def build_file_filter(self, file_ids: list[str] | None = None) -> dict | None:
        return build_file_filter(file_ids)

    def search_dense(self, query: str, limit: int, metadata_filter: dict | None) -> list[dict]:
        return search_dense(query, limit, metadata_filter)

    def search_sparse(self, query: str, limit: int, metadata_filter: dict | None) -> list[dict]:
        return search_sparse(query, limit, metadata_filter)

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: dict | None,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        return search_hybrid(query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        return _sparse_uses_store(sparse)


def close_store():
    global _client, _ready
    _stores.clear()
    _client = None
    _ready = False


def drop_collections() -> None:
    client = _get_chroma_client()
    collection_name = _chunks_collection()
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    _stores.clear()


def ensure_app_collection(app_id: str) -> str:
    collection_name = collection_name_for_app(app_id)
    with app_collection(app_id):
        _ensure_collection()
    return collection_name


def app_collection_exists(app_id: str) -> bool:
    collection_name = collection_name_for_app(app_id)
    names = [getattr(collection, "name", collection) for collection in _get_chroma_client().list_collections()]
    return collection_name in names


def drop_app_collection(app_id: str) -> bool:
    collection_name = collection_name_for_app(app_id)
    if not app_collection_exists(app_id):
        return False
    _get_chroma_client().delete_collection(collection_name)
    _stores.clear()
    return True


def init_store(
    dense: Dense | None = None,
    sparse: Sparse | None = None,
    persist_dir: str | None = None,
):
    global _ready
    _configure_store(persist_dir)
    _init_dense(dense)
    _init_sparse(sparse)
    _ready = True


def init_search():
    init_store()


def _configure_store(
    persist_dir: str | None = None,
):
    global _persist_dir
    if persist_dir is not None:
        _persist_dir = persist_dir


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


def _get_langchain_dense():
    return _get_dense()


def _get_sparse() -> Sparse | None:
    return _sparse


def _sparse_uses_store(sparse: Sparse | None = None) -> bool:
    candidate = _get_sparse() if sparse is None else sparse
    return isinstance(candidate, SparseEmbeddingFunction)


def sparse_uses_store(sparse: Sparse | None = None) -> bool:
    return _sparse_uses_store(sparse)


def _store_for(mode: SearchMode):
    _require_search_ready()
    return _collection()


def _get_store_unchecked(mode: SearchMode):
    return _collection()


def _get_chroma_client():
    global _client
    if _client is None:
        import chromadb

        _client = chromadb.PersistentClient(path=_persist_path(_persist_dir))
    return _client


def _persist_path(persist_dir: str | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if persist_dir is None:
        return None
    path = Path(persist_dir).expanduser()
    if not path.is_absolute():
        path = project_root / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _ensure_collection() -> None:
    client = _get_chroma_client()
    collection_name = _chunks_collection()
    if _sparse_uses_store():
        try:
            client.get_or_create_collection(
                name=collection_name,
                schema=_chroma_schema(),
                embedding_function=None,
            )
        except Exception as exc:
            if "Sparse vector indexing is not enabled in local" in str(exc):
                raise RuntimeError(
                    "本地 Chroma 不支持 vector sparse。Chroma 本地配置请使用 sparse.type=bm25。"
                ) from exc
            raise
        return
    client.get_or_create_collection(name=collection_name, embedding_function=None)


def _chroma_schema():
    from chromadb import K, Schema, SparseVectorIndexConfig

    return Schema().create_index(
        SparseVectorIndexConfig(
            embedding_function=_get_sparse(),
            source_key=K.DOCUMENT,
        ),
        key=SPARSE_VECTOR_KEY,
    )


def _distance_to_score(distance: float) -> float:
    return 1.0 / (1.0 + float(distance))


def _search_config_value(key: str, default):
    return SEARCH_CONFIG.get(key, default)


def search_dense(query: str, limit: int, metadata_filter: dict | None) -> list[dict]:
    rows = _collection().query(
        query_embeddings=[_get_dense().embed_query(query)],
        n_results=limit,
        where=metadata_filter,
        include=["documents", "metadatas", "distances"],
    )
    return _query_rows_to_items(rows)


def search_sparse(query: str, limit: int, metadata_filter: dict | None) -> list[dict]:
    docs = _search_sparse_or_hybrid("sparse", query, limit, metadata_filter)
    return _documents_with_scores_to_items(docs)


def search_hybrid(
    query: str,
    limit: int,
    metadata_filter: dict | None,
    dense_weight: float,
    sparse_weight: float,
    rrf_k: int,
) -> list[dict]:
    docs = _search_sparse_or_hybrid("hybrid", query, limit, metadata_filter, dense_weight, sparse_weight, rrf_k)
    return _documents_with_scores_to_items(docs)


def _search_sparse_or_hybrid(
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
                Knn(query=_get_dense().embed_query(query), limit=limit, return_rank=True),
                Knn(query=query, key=SPARSE_VECTOR_KEY, limit=limit, return_rank=True),
            ],
            weights=[
                float(dense_weight if dense_weight is not None else _search_config_value("dense_weight", 0.5)),
                float(sparse_weight if sparse_weight is not None else _search_config_value("sparse_weight", 0.5)),
            ],
            k=int(rrf_k if rrf_k is not None else _search_config_value("rrf_k", 60)),
        )
    search = Search(where=metadata_filter, rank=rank, limit=limit, select=[K.DOCUMENT, K.SCORE, "metadata"])
    rows = _collection().search(search).rows()
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


def add_file_chunks(chunks: list[dict], file_id: str) -> int:
    if not chunks:
        return 0
    if not file_id:
        raise ValueError("file_id is required")
    _require_search_ready()
    delete_file_chunks(file_id)
    _collection().add(
        ids=[_point_id(chunk["id"]) for chunk in chunks],
        documents=[chunk["content"] for chunk in chunks],
        metadatas=[_metadata_for_chunk(chunk, file_id) for chunk in chunks],
        embeddings=_get_dense().embed_documents([chunk["content"] for chunk in chunks]),
    )
    return len(chunks)


def delete_file_chunks(file_id: str) -> int:
    return _delete_by_filter(_file_payload_filter([file_id]))


def get_total_chunks(file_ids: list[str] | None = None) -> int:
    return len(get_search_documents(build_file_filter(file_ids)))


def get_search_documents(metadata_filter: dict | None) -> list[dict]:
    rows = _collection_get(metadata_filter)
    return _rows_to_documents(rows)


def list_chunks(file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    start = int(cursor) if cursor else 0
    rows = _collection_get_page(build_file_filter(file_ids), limit=limit + 1, offset=start)
    ids = rows.get("ids") or []
    documents = _rows_to_documents(rows)
    return {
        "documents": documents[:limit],
        "next_cursor": str(start + limit) if len(ids) > limit else None,
        "has_more": len(ids) > limit,
    }


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


def build_file_filter(file_ids: list[str] | None = None) -> dict | None:
    if file_ids is None:
        return None
    if not file_ids:
        raise ValueError("file_ids cannot be empty")
    return _file_payload_filter(file_ids)


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


def _delete_by_filter(metadata_filter: dict) -> int:
    before = len((_collection_get(metadata_filter).get("ids") or []))
    if before:
        _collection().delete(where=metadata_filter)
    return before


def _collection_get(metadata_filter: dict | None) -> dict:
    if metadata_filter is None:
        return _collection().get(include=["documents", "metadatas"])
    return _collection().get(where=metadata_filter, include=["documents", "metadatas"])


def _collection_get_page(metadata_filter: dict | None, *, limit: int, offset: int) -> dict:
    if metadata_filter is None:
        return _collection().get(limit=limit, offset=offset, include=["documents", "metadatas"])
    return _collection().get(where=metadata_filter, limit=limit, offset=offset, include=["documents", "metadatas"])


def _collection():
    return _get_chroma_client().get_collection(_chunks_collection())


def _chunks_collection() -> str:
    return current_collection()


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
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
