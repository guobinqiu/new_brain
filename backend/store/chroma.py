"""Chroma-backed document storage through LangChain Chroma."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from chromadb.utils.embedding_functions import SparseEmbeddingFunction
from config import QDRANT_COMMON_COLLECTION, QDRANT_SCOPED_COLLECTION, SEARCH_CONFIG
from dense.base import Dense
from dense.huggingface import HuggingFaceDense
from langchain_chroma import Chroma
from langchain_core.documents import Document
from sparse.base import Sparse


CollectionType = Literal["common", "scoped"]
SearchMode = Literal["dense", "sparse", "hybrid"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

COLLECTION_BY_TYPE: dict[CollectionType, str] = {
    "common": QDRANT_COMMON_COLLECTION,
    "scoped": QDRANT_SCOPED_COLLECTION,
}

_dense: Dense | None = None
_sparse: Sparse | None = None
_persist_dir: str | None = None
_stores: dict[tuple[CollectionType, SearchMode], object] = {}
_client = None
_ready = False
SPARSE_VECTOR_KEY = "sparse_embedding"


class ChromaStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        persist_dir: str | None = None,
        common_collection: str | None = None,
        scoped_collection: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.persist_dir = persist_dir
        self.common_collection = common_collection or QDRANT_COMMON_COLLECTION
        self.scoped_collection = scoped_collection or QDRANT_SCOPED_COLLECTION

    def start(self) -> None:
        self.dense.start()
        init_store(
            dense=self.dense,
            sparse=self.sparse,
            persist_dir=self.persist_dir,
            common_collection=self.common_collection,
            scoped_collection=self.scoped_collection,
        )

    def stop(self) -> None:
        close_store()
        self.dense.stop()

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

    def get_search_documents(self, collection_type: CollectionType, metadata_filter: dict) -> list[dict]:
        return get_search_documents(collection_type, metadata_filter)

    def build_common_filter(self, namespace: str) -> dict:
        return build_common_filter(namespace)

    def build_scoped_filter(self, namespace: str, scope_ids: list[str]) -> dict:
        return build_scoped_filter(namespace, scope_ids)

    def search_dense(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: dict) -> list[dict]:
        return search_dense(collection_type, query, limit, metadata_filter)

    def search_sparse(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: dict) -> list[dict]:
        return search_sparse(collection_type, query, limit, metadata_filter)

    def search_hybrid(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: dict) -> list[dict]:
        return search_hybrid(collection_type, query, limit, metadata_filter)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        return _sparse_uses_store(sparse)


def close_store():
    global _client, _ready
    _stores.clear()
    _client = None
    _ready = False


def init_store(
    dense: Dense | None = None,
    sparse: Sparse | None = None,
    persist_dir: str | None = None,
    common_collection: str | None = None,
    scoped_collection: str | None = None,
):
    global _ready
    _configure_store(persist_dir, common_collection, scoped_collection)
    _init_dense(dense)
    _init_sparse(sparse)
    _ensure_collection("common")
    _ensure_collection("scoped")
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


def _configure_store(
    persist_dir: str | None = None,
    common_collection: str | None = None,
    scoped_collection: str | None = None,
):
    global _persist_dir, COLLECTION_BY_TYPE
    if persist_dir is not None:
        _persist_dir = persist_dir
    if common_collection is not None:
        COLLECTION_BY_TYPE["common"] = common_collection
    if scoped_collection is not None:
        COLLECTION_BY_TYPE["scoped"] = scoped_collection


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
    candidate = _get_sparse() if sparse is None else sparse
    return isinstance(candidate, SparseEmbeddingFunction)


def _store_for(collection_type: CollectionType, mode: SearchMode):
    _require_search_ready()
    key = (collection_type, mode)
    if key not in _stores:
        raise RuntimeError("store is not initialized")
    return _stores[key]


def _get_store_unchecked(collection_type: CollectionType, mode: SearchMode):
    key = (collection_type, mode)
    if key not in _stores:
        store = Chroma(
            collection_name=COLLECTION_BY_TYPE[collection_type],
            embedding_function=_get_langchain_dense(),
            client=_get_chroma_client(),
        )
        _stores[key] = store
    return _stores[key]


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


def _ensure_collection(collection_type: CollectionType) -> None:
    client = _get_chroma_client()
    collection_name = COLLECTION_BY_TYPE[collection_type]
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
                    "Chroma Cloud supports sparse vector indexing, but Chroma local mode does not. "
                    "Use sparse.type=bm25 for local Chroma, or use Chroma Cloud / a Chroma service "
                    "with sparse vector indexing enabled."
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


def _common_store(mode: SearchMode = "hybrid"):
    return _store_for("common", mode)


def _scoped_store(mode: SearchMode = "hybrid"):
    return _store_for("scoped", mode)


def search_dense(collection_type: CollectionType, query: str, limit: int, metadata_filter: dict) -> list[dict]:
    docs = [
        (doc, _distance_to_score(score))
        for doc, score in _store_for(collection_type, "dense").similarity_search_with_score(query, k=limit, filter=metadata_filter)
    ]
    return _documents_with_scores_to_items(docs, collection_type)


def search_sparse(collection_type: CollectionType, query: str, limit: int, metadata_filter: dict) -> list[dict]:
    docs = _search_sparse_or_hybrid(collection_type, "sparse", query, limit, metadata_filter)
    return _documents_with_scores_to_items(docs, collection_type)


def search_hybrid(collection_type: CollectionType, query: str, limit: int, metadata_filter: dict) -> list[dict]:
    docs = _search_sparse_or_hybrid(collection_type, "hybrid", query, limit, metadata_filter)
    return _documents_with_scores_to_items(docs, collection_type)


def _search_sparse_or_hybrid(collection_type: CollectionType, mode: SearchMode, query: str, limit: int, metadata_filter: dict):
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
                float(_search_config_value("dense_weight", 0.5)),
                float(_search_config_value("sparse_weight", 0.5)),
            ],
            k=int(_search_config_value("rrf_k", 60)),
        )
    search = Search(where=metadata_filter, rank=rank, limit=limit, select=[K.DOCUMENT, K.SCORE, "metadata"])
    rows = _collection(_store_for(collection_type, mode)).search(search).rows()
    records = rows[0] if rows else []
    results = []
    for rank_index, record in enumerate(records):
        if record["document"] is None:
            continue
        results.append((
            Document(
                page_content=record["document"],
                metadata=record["metadata"] or {},
                id=record["id"],
            ),
            1.0 / (rank_index + 1),
        ))
    return results


def add_common_documents(chunks: list[dict], namespace: str = "default") -> int:
    if not chunks:
        return 0
    _require_search_ready()
    filename = _filename_from_chunks(chunks)
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
    delete_scoped_document(filename, namespace, scope_id)
    _scoped_store(_write_mode()).add_documents(
        _to_documents(chunks, namespace, scope_id),
        ids=[_point_id(chunk["id"]) for chunk in chunks],
    )
    return len(chunks)


def delete_common_document(filename: str, namespace: str = "default") -> int:
    return _delete_by_filter("common", _payload_filter(namespace=namespace, filename=filename))


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
    total = len(get_search_documents("common", _payload_filter(namespace=namespace)))
    if scope_ids:
        total += len(get_search_documents("scoped", _payload_filter(namespace=namespace, scope_ids=scope_ids)))
    return total


def get_search_documents(collection_type: CollectionType, metadata_filter: dict) -> list[dict]:
    store = _store_for(collection_type, "dense")
    rows = _collection_get(store, metadata_filter)
    documents = rows.get("documents") or []
    metadatas = rows.get("metadatas") or []
    ids = rows.get("ids") or []
    results = []
    for row_id, content, metadata in zip(ids, documents, metadatas):
        metadata = dict(metadata or {})
        source_id = metadata.get("source_id") or metadata.get("id") or row_id
        results.append({
            "id": source_id,
            "content": content or "",
            "metadata": metadata,
            "collection_type": collection_type,
        })
    return results


def build_common_filter(namespace: str) -> dict:
    return _payload_filter(namespace=namespace)


def build_scoped_filter(namespace: str, scope_ids: list[str]) -> dict:
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
    return "dense"


def _filename_from_chunks(chunks: list[dict]) -> str:
    filename = chunks[0].get("metadata", {}).get("filename")
    if not filename:
        raise ValueError("chunk metadata.filename is required")
    return filename


def _payload_filter(
    namespace: str,
    scope_ids: list[str | None] | None = None,
    filename: str | None = None,
) -> dict:
    conditions: list[dict] = [{"namespace": {"$eq": namespace}}]
    cleaned_scope_ids = [scope_id for scope_id in scope_ids or [] if scope_id]
    if cleaned_scope_ids:
        conditions.append({"scope_id": {"$in": cleaned_scope_ids}})
    if filename:
        conditions.append({"filename": {"$eq": filename}})
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _delete_by_filter(collection_type: CollectionType, metadata_filter: dict) -> int:
    store = _store_for(collection_type, "dense")
    before = len((_collection_get(store, metadata_filter).get("ids") or []))
    if before:
        _collection(store).delete(where=metadata_filter)
    return before


def _list_documents(collection_type: CollectionType, metadata_filter: dict) -> list[dict]:
    rows = _collection_get(_store_for(collection_type, "dense"), metadata_filter)
    metadatas = rows.get("metadatas") or []
    seen: dict[tuple[str, str | None], dict] = {}
    for metadata in metadatas:
        metadata = dict(metadata or {})
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


def _collection_get(store, metadata_filter: dict) -> dict:
    return _collection(store).get(where=metadata_filter, include=["documents", "metadatas"])


def _collection(store):
    collection = getattr(store, "_collection", None)
    if collection is None:
        raise RuntimeError("Chroma collection is not initialized")
    return collection


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


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
