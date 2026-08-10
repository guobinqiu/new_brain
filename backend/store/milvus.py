"""Milvus-backed document storage through LangChain Milvus."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from config import QDRANT_COMMON_COLLECTION, QDRANT_SCOPED_COLLECTION, SEARCH_CONFIG
from dense.base import Dense
from dense.huggingface import HuggingFaceDense
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
_uri: str | None = None
_stores: dict[tuple[CollectionType, SearchMode], object] = {}
_builtin_function = None
_ready = False


class MilvusStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        uri: str | None = None,
        common_collection: str | None = None,
        scoped_collection: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.uri = uri or "http://localhost:19530"
        self.common_collection = common_collection or QDRANT_COMMON_COLLECTION
        self.scoped_collection = scoped_collection or QDRANT_SCOPED_COLLECTION

    def start(self) -> None:
        self.dense.start()
        init_store(
            dense=self.dense,
            sparse=self.sparse,
            uri=self.uri,
            common_collection=self.common_collection,
            scoped_collection=self.scoped_collection,
        )

    def stop(self) -> None:
        close_store()
        self.dense.stop()

    def drop_collections(self) -> None:
        _configure_store(self.uri, self.common_collection, self.scoped_collection)
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

    def get_search_documents(self, collection_type: CollectionType, metadata_filter: str) -> list[dict]:
        return get_search_documents(collection_type, metadata_filter)

    def build_common_filter(self, namespace: str) -> str:
        return build_common_filter(namespace)

    def build_scoped_filter(self, namespace: str, scope_ids: list[str]) -> str:
        return build_scoped_filter(namespace, scope_ids)

    def search_dense(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return search_dense(collection_type, query, limit, metadata_filter)

    def search_sparse(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return search_sparse(collection_type, query, limit, metadata_filter)

    def search_hybrid(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return search_hybrid(collection_type, query, limit, metadata_filter)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        return _sparse_uses_store(sparse)


def close_store():
    global _builtin_function, _ready
    _close_store_clients()
    _stores.clear()
    if _is_lite_uri(_uri):
        _release_lite_server(_connection_uri(_uri))
    _builtin_function = None
    _ready = False


def drop_collections() -> None:
    from pymilvus import MilvusClient

    uri = _connection_uri(_uri)
    client = MilvusClient(uri=uri)
    try:
        for collection_name in COLLECTION_BY_TYPE.values():
            if client.has_collection(collection_name):
                client.drop_collection(collection_name)
    finally:
        client.close()
    _stores.clear()


def _close_store_clients() -> None:
    seen: set[int] = set()
    for store in _stores.values():
        for attr in ("client", "_milvus_client"):
            client = getattr(store, attr, None)
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            close = getattr(client, "close", None)
            if callable(close):
                close()


def init_store(
    dense: Dense | None = None,
    sparse: Sparse | None = None,
    uri: str | None = None,
    common_collection: str | None = None,
    scoped_collection: str | None = None,
):
    global _ready
    _configure_store(uri, common_collection, scoped_collection)
    _init_dense(dense)
    _init_sparse(sparse)
    if _sparse_uses_store():
        _get_store_unchecked("common", "hybrid")
        _get_store_unchecked("scoped", "hybrid")
        ensure_collections()
        _get_store_unchecked("common", "dense")
        _get_store_unchecked("scoped", "dense")
        _get_store_unchecked("common", "sparse")
        _get_store_unchecked("scoped", "sparse")
    else:
        _get_store_unchecked("common", "dense")
        _get_store_unchecked("scoped", "dense")
        ensure_collections()
    _ready = True


def init_search():
    init_store()


def _configure_store(
    uri: str | None = None,
    common_collection: str | None = None,
    scoped_collection: str | None = None,
):
    global _uri, COLLECTION_BY_TYPE
    if uri is not None:
        _uri = uri
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
    if candidate is None:
        return False
    from langchain_milvus.utils.sparse import BaseSparseEmbedding

    return isinstance(candidate, BaseSparseEmbedding) or callable(
        getattr(candidate, "as_milvus_builtin_function", None)
    )


def sparse_uses_store(sparse: Sparse | None = None) -> bool:
    return _sparse_uses_store(sparse)


def _store_for(collection_type: CollectionType, mode: SearchMode):
    _require_search_ready()
    key = (collection_type, mode)
    if key not in _stores:
        raise RuntimeError("store is not initialized")
    return _stores[key]


def ensure_collections() -> None:
    for collection_type in COLLECTION_BY_TYPE:
        _ensure_collection(collection_type)


def _ensure_collection(collection_type: CollectionType) -> None:
    store = _get_store_unchecked(collection_type, _write_mode())
    if store.client.has_collection(store.collection_name):
        return
    store._create_collection(
        embeddings=_schema_probe_embeddings(),
        metadatas=[_schema_probe_metadata(collection_type)],
    )
    store._extract_fields()
    store._create_index()
    store._create_search_params()
    store._load()


def _schema_probe_embeddings() -> list:
    if _sparse_uses_store():
        dense_embedding = _get_dense().embed_query("schema initialization")
        if _milvus_builtin_function() is not None:
            return [[dense_embedding]]
        sparse = _get_sparse()
        if sparse is None:
            raise RuntimeError("sparse is not initialized")
        return [[dense_embedding], [sparse.embed_query("schema initialization")]]
    return [[_get_dense().embed_query("schema initialization")]]


def _schema_probe_metadata(collection_type: CollectionType) -> dict:
    metadata = {
        "source_id": f"__schema__:{collection_type}",
        "namespace": "__schema__",
        "filename": "__schema__.txt",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if collection_type == "scoped":
        metadata["scope_id"] = "__schema__"
    return metadata


def _get_store_unchecked(collection_type: CollectionType, mode: SearchMode):
    key = (collection_type, mode)
    if key not in _stores:
        Milvus = _load_milvus_class()

        store = Milvus(
            embedding_function=_embedding_function_for_mode(mode),
            collection_name=COLLECTION_BY_TYPE[collection_type],
            connection_args={"uri": _connection_uri(_uri)},
            index_params=_index_params_for_mode(mode),
            auto_id=False,
            enable_dynamic_field=True,
            vector_field=_vector_field_for_mode(mode),
            builtin_function=_builtin_function_for_mode(mode),
        )
        _stores[key] = store
    return _stores[key]


def _load_milvus_class():
    from langchain_milvus import Milvus

    return Milvus


def _connection_uri(uri: str | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if uri is None or "://" in uri:
        return uri
    path = Path(uri).expanduser()
    if not path.is_absolute():
        path = project_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _is_lite_uri(uri: str | None) -> bool:
    return bool(uri and "://" not in uri and uri.endswith(".db"))


def _release_lite_server(uri: str | None) -> None:
    if not uri:
        return
    from milvus_lite.server_manager import server_manager_instance

    server_manager_instance.release_server(uri)


def _embedding_function_for_mode(mode: SearchMode):
    if not _sparse_uses_store():
        return _get_langchain_dense()
    if mode == "dense":
        return _get_langchain_dense()
    if mode == "sparse":
        return None if _milvus_builtin_function() is not None else _get_sparse()
    return [_get_langchain_dense()] if _milvus_builtin_function() is not None else [_get_langchain_dense(), _get_sparse()]


def _vector_field_for_mode(mode: SearchMode):
    if not _sparse_uses_store():
        return "vector"
    if mode == "dense":
        return "dense"
    if mode == "sparse":
        return "sparse"
    return ["dense", "sparse"]


def _builtin_function_for_mode(mode: SearchMode):
    builtin_function = _milvus_builtin_function()
    if builtin_function is None:
        return None
    if mode in ("sparse", "hybrid"):
        return builtin_function
    return None


def _milvus_builtin_function():
    global _builtin_function
    sparse = _get_sparse()
    unwrap = getattr(sparse, "as_milvus_builtin_function", None)
    if callable(unwrap):
        if _builtin_function is None:
            _builtin_function = unwrap()
        return _builtin_function
    return None


def _search_params_for_mode(mode: SearchMode):
    if not _sparse_uses_store():
        return None
    if mode == "dense":
        return {"metric_type": "L2", "params": {}}
    sparse_params = _sparse_search_params()
    if mode == "sparse":
        return sparse_params
    return [
        {"metric_type": "L2", "params": {}},
        sparse_params,
    ]


def _sparse_search_params():
    if _milvus_builtin_function() is not None:
        return {"metric_type": "BM25", "params": {}}
    return {"metric_type": "IP", "params": {}}


def _index_params_for_mode(mode: SearchMode):
    if not _is_lite_uri(_uri):
        return None
    dense_index = {"metric_type": "L2", "index_type": "FLAT", "params": {}}
    if not _sparse_uses_store() or mode == "dense":
        return dense_index
    sparse_index = _sparse_index_params()
    if mode == "sparse":
        return sparse_index
    return [dense_index, sparse_index]


def _sparse_index_params():
    if _milvus_builtin_function() is not None:
        return {"metric_type": "BM25", "index_type": "AUTOINDEX", "params": {}}
    return {
        "metric_type": "IP",
        "index_type": "SPARSE_INVERTED_INDEX",
        "params": {"drop_ratio_build": 0.2},
    }


def _query_data_for_mode(mode: SearchMode, query: str):
    if mode == "dense":
        return _get_dense().embed_query(query)
    if _milvus_builtin_function() is not None:
        return query
    sparse = _get_sparse()
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    return sparse.embed_query(query)


def _documents_from_milvus_rows(rows, mode: SearchMode, collection_type: CollectionType) -> list[dict]:
    if not rows:
        return []
    docs = []
    for rank, row in enumerate(rows[0], start=1):
        entity = dict(row.get("entity") or {})
        metadata = _metadata_from_row(entity)
        doc = Document(
            page_content=entity.get("text") or "",
            metadata=metadata,
            id=str(row.get("id") or entity.get("pk") or metadata.get("source_id") or ""),
        )
        docs.append((doc, _milvus_score(row.get("distance", 0.0), mode, rank)))
    return _documents_with_scores_to_items(docs, collection_type)


def _milvus_score(distance: float, mode: SearchMode, rank: int) -> float:
    if mode == "dense":
        return 1.0 / (1.0 + float(distance))
    return 1.0 / rank


def _common_store(mode: SearchMode = "hybrid"):
    return _store_for("common", mode)


def _scoped_store(mode: SearchMode = "hybrid"):
    return _store_for("scoped", mode)


def search_dense(collection_type: CollectionType, query: str, limit: int, metadata_filter: str) -> list[dict]:
    if _sparse_uses_store():
        rows = _single_vector_search(collection_type, "dense", query, limit, metadata_filter)
        return _documents_from_milvus_rows(rows, "dense", collection_type)
    docs = _store_for(collection_type, "dense").similarity_search_with_score(
        query,
        k=limit,
        expr=metadata_filter,
        param=_search_params_for_mode("dense"),
    )
    return _documents_with_scores_to_items(docs, collection_type)


def search_sparse(collection_type: CollectionType, query: str, limit: int, metadata_filter: str) -> list[dict]:
    rows = _single_vector_search(collection_type, "sparse", query, limit, metadata_filter)
    return _documents_from_milvus_rows(rows, "sparse", collection_type)


def search_hybrid(collection_type: CollectionType, query: str, limit: int, metadata_filter: str) -> list[dict]:
    rows = _hybrid_search(collection_type, query, limit, metadata_filter)
    return _documents_from_milvus_rows(rows, "hybrid", collection_type)


def _single_vector_search(collection_type: CollectionType, mode: SearchMode, query: str, limit: int, metadata_filter: str):
    store = _store_for(collection_type, mode)
    return store.client.search(
        store.collection_name,
        data=[_query_data_for_mode(mode, query)],
        anns_field=_vector_field_for_mode(mode),
        search_params=_search_params_for_mode(mode),
        limit=limit,
        filter=metadata_filter,
        output_fields=["*"],
    )


def _hybrid_search(collection_type: CollectionType, query: str, limit: int, metadata_filter: str):
    from pymilvus import AnnSearchRequest, WeightedRanker

    store = _store_for(collection_type, "hybrid")
    reqs = [
        AnnSearchRequest(
            data=[_get_dense().embed_query(query)],
            anns_field="dense",
            param={"metric_type": "L2", "params": {}},
            limit=limit,
            filter=metadata_filter,
        ),
        AnnSearchRequest(
            data=[_query_data_for_mode("sparse", query)],
            anns_field="sparse",
            param=_sparse_search_params(),
            limit=limit,
            filter=metadata_filter,
        ),
    ]
    return store.client.hybrid_search(
        store.collection_name,
        reqs=reqs,
        ranker=WeightedRanker(
            float(SEARCH_CONFIG.get("dense_weight", 0.5)),
            float(SEARCH_CONFIG.get("sparse_weight", 0.5)),
        ),
        limit=limit,
        output_fields=["*"],
    )


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


def get_search_documents(collection_type: CollectionType, metadata_filter: str) -> list[dict]:
    store = _store_for(collection_type, "dense")
    rows = store._milvus_client.query(
        collection_name=store.collection_name,
        filter=metadata_filter,
        output_fields=["*"],
    )
    results = []
    for row in rows:
        metadata = _metadata_from_row(row)
        results.append({
            "id": str(row.get("pk") or metadata.get("source_id") or metadata.get("id", "")),
            "content": row.get("text") or "",
            "metadata": metadata,
            "collection_type": collection_type,
        })
    return results


def build_common_filter(namespace: str) -> str:
    return _payload_filter(namespace=namespace)


def build_scoped_filter(namespace: str, scope_ids: list[str]) -> str:
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
) -> str:
    conditions: list[str] = [f'namespace == {_milvus_literal(namespace)}']
    cleaned_scope_ids = [scope_id for scope_id in scope_ids or [] if scope_id]
    if cleaned_scope_ids:
        conditions.append(f"scope_id in {[str(scope_id) for scope_id in cleaned_scope_ids]!r}")
    if filename:
        conditions.append(f'filename == {_milvus_literal(filename)}')
    return " and ".join(conditions)


def _delete_by_filter(collection_type: CollectionType, metadata_filter: str) -> int:
    store = _store_for(collection_type, "dense")
    ids = store.get_pks(expr=metadata_filter) or []
    if ids:
        store.delete(ids=ids)
    return len(ids)


def _list_documents(collection_type: CollectionType, metadata_filter: str) -> list[dict]:
    documents = get_search_documents(collection_type, metadata_filter)
    seen: dict[tuple[str, str | None], dict] = {}
    for document in documents:
        metadata = dict(document.get("metadata") or {})
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


def _metadata_from_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"pk", "text", "vector"}
    }


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


def _milvus_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
