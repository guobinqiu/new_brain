"""Milvus-backed document storage through native pymilvus client."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal

from config import QDRANT_CHUNKS_COLLECTION
from dense.base import Dense
from dense.huggingface import HuggingFaceDense
from sparse.base import Sparse
from store.files import count_files_from_documents, list_files_from_documents
from store.startup import run_with_startup_retry


SearchMode = Literal["dense", "sparse", "hybrid"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_client = None
_dense: Dense | None = None
_sparse: Sparse | None = None
_uri: str | None = None
_timeout: int | None = None
_ready = False


class MilvusStore:
    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        uri: str | None = None,
        timeout: int | None = None,
        chunks_collection: str | None = None,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.uri = uri or "http://localhost:19530"
        self.timeout = timeout
        self.chunks_collection = chunks_collection or QDRANT_CHUNKS_COLLECTION

    def start(self) -> None:
        init_store(
            dense=self.dense,
            sparse=self.sparse,
            uri=self.uri,
            timeout=self.timeout,
            chunks_collection=self.chunks_collection,
        )

    def stop(self) -> None:
        close_store()

    def drop_collections(self) -> None:
        _configure_store(self.uri, self.chunks_collection, self.timeout)
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
        return list_files_from_documents(get_search_documents(""), limit=limit, cursor=cursor)

    def count_files(self) -> int:
        return count_files_from_documents(get_search_documents(""))

    def get_search_documents(self, metadata_filter: str) -> list[dict]:
        return get_search_documents(metadata_filter)

    def build_file_filter(self, file_ids: list[str] | None = None) -> str:
        return build_file_filter(file_ids)

    def search_dense(self, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return search_dense(query, limit, metadata_filter)

    def search_sparse(self, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return search_sparse(query, limit, metadata_filter)

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: str,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        return search_hybrid(query, limit, metadata_filter, dense_weight, sparse_weight)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        return _sparse_uses_store(sparse)


def close_store():
    global _client, _ready
    if _client is not None:
        close = getattr(_client, "close", None)
        if callable(close):
            close()
    _client = None
    if _is_lite_uri(_uri):
        _release_lite_server(_connection_uri(_uri))
    _ready = False


def drop_collections() -> None:
    client = get_milvus_client()
    if client.has_collection(QDRANT_CHUNKS_COLLECTION):
        client.drop_collection(QDRANT_CHUNKS_COLLECTION)


def init_store(
    dense: Dense | None = None,
    sparse: Sparse | None = None,
    uri: str | None = None,
    timeout: int | None = None,
    chunks_collection: str | None = None,
):
    global _ready
    _configure_store(uri, chunks_collection, timeout)
    _init_dense(dense)
    _init_sparse(sparse)
    run_with_startup_retry(ensure_collections)
    _ready = True


def init_search():
    init_store()


def _configure_store(
    uri: str | None = None,
    chunks_collection: str | None = None,
    timeout: int | None = None,
):
    global _uri, _timeout, QDRANT_CHUNKS_COLLECTION
    if uri is not None:
        _uri = uri
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
    from sparse.milvus_bge_m3 import MilvusBGEM3Sparse
    from sparse.milvus_bm25 import MilvusBM25Sparse

    return isinstance(_get_sparse() if sparse is None else sparse, (MilvusBGEM3Sparse, MilvusBM25Sparse))


def sparse_uses_store(sparse: Sparse | None = None) -> bool:
    return _sparse_uses_store(sparse)


def get_milvus_client():
    global _client
    if _client is None:
        from pymilvus import MilvusClient

        _client = MilvusClient(uri=_connection_uri(_uri), timeout=_timeout)
    return _client


def ensure_collections() -> None:
    client = get_milvus_client()
    if not client.has_collection(QDRANT_CHUNKS_COLLECTION):
        client.create_collection(
            collection_name=QDRANT_CHUNKS_COLLECTION,
            schema=_collection_schema(),
            index_params=_collection_index_params(),
            timeout=_timeout,
        )
    client.load_collection(QDRANT_CHUNKS_COLLECTION, timeout=_timeout)


def _collection_schema():
    from pymilvus import DataType, Function, FunctionType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field(field_name="pk", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535, **_text_field_kwargs())
    schema.add_field(field_name="file_id", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
    schema.add_field(field_name="filename", datatype=DataType.VARCHAR, max_length=1024)
    schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=64, nullable=True)
    schema.add_field(field_name=_dense_vector_field(), datatype=DataType.FLOAT_VECTOR, dim=_dense_vector_size())
    if _sparse_uses_store():
        schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
    if _sparse_is_builtin_bm25():
        schema.add_function(Function(
            name="bm25_function",
            function_type=FunctionType.BM25,
            input_field_names="text",
            output_field_names="sparse",
        ))
    return schema


def _text_field_kwargs() -> dict:
    if not _sparse_is_builtin_bm25():
        return {}
    sparse = _get_sparse()
    kwargs = {"enable_analyzer": True, "enable_match": True}
    analyzer_params = getattr(sparse, "analyzer_params", None)
    if analyzer_params is not None:
        kwargs["analyzer_params"] = analyzer_params
    return kwargs


def _collection_index_params():
    from pymilvus import MilvusClient

    index_params = MilvusClient.prepare_index_params()
    for field_name, params in _index_specs():
        index_params.add_index(field_name=field_name, **params)
    return index_params


def _index_specs() -> list[tuple[str, dict]]:
    specs = [(_dense_vector_field(), _dense_index_params())]
    if _sparse_uses_store():
        specs.append(("sparse", _sparse_index_params()))
    specs.append(("file_id", {"index_type": "INVERTED"}))
    return specs


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


def _vector_field_for_mode(mode: SearchMode):
    if not _sparse_uses_store():
        return "vector"
    if mode == "dense":
        return "dense"
    if mode == "sparse":
        return "sparse"
    return ["dense", "sparse"]


def _dense_vector_field() -> str:
    return "dense" if _sparse_uses_store() else "vector"


def _dense_vector_size() -> int:
    return len(_get_dense().embed_query("dimension probe"))


def _search_params_for_mode(mode: SearchMode):
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
    if _sparse_is_builtin_bm25():
        return {"metric_type": "BM25", "params": {}}
    return {"metric_type": "IP", "params": {}}


def _index_params_for_mode(mode: SearchMode):
    dense_index = _dense_index_params()
    if not _sparse_uses_store() or mode == "dense":
        return dense_index
    sparse_index = _sparse_index_params()
    if mode == "sparse":
        return sparse_index
    return [dense_index, sparse_index]


def _dense_index_params() -> dict:
    if _is_lite_uri(_uri):
        return {"metric_type": "L2", "index_type": "FLAT", "params": {}}
    return {"metric_type": "L2", "index_type": "AUTOINDEX", "params": {}}


def _sparse_index_params():
    if _sparse_is_builtin_bm25():
        return {
            "metric_type": "BM25",
            "index_type": "SPARSE_INVERTED_INDEX",
            "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
        }
    return {
        "metric_type": "IP",
        "index_type": "SPARSE_INVERTED_INDEX",
        "params": {"drop_ratio_build": 0.2},
    }


def _query_data_for_mode(mode: SearchMode, query: str):
    if mode == "dense":
        return _get_dense().embed_query(query)
    if _sparse_is_builtin_bm25():
        return query
    sparse = _get_sparse()
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    return sparse.embed_query(query)


def _sparse_is_builtin_bm25() -> bool:
    from sparse.milvus_bm25 import MilvusBM25Sparse

    sparse = _get_sparse()
    return isinstance(sparse, MilvusBM25Sparse)


def _documents_from_milvus_rows(rows, mode: SearchMode) -> list[dict]:
    if not rows:
        return []
    items = []
    for rank, row in enumerate(rows[0], start=1):
        entity = dict(row.get("entity") or {})
        metadata = _metadata_from_row(entity)
        items.append({
            "id": str(row.get("id") or entity.get("pk") or ""),
            "content": entity.get("text") or "",
            "metadata": metadata,
            "_score": _milvus_score(row.get("distance", 0.0), mode, rank),
        })
    return items


def _milvus_score(distance: float, mode: SearchMode, rank: int) -> float:
    if mode == "dense":
        return 1.0 / (1.0 + float(distance))
    return 1.0 / rank


def search_dense(query: str, limit: int, metadata_filter: str) -> list[dict]:
    rows = _single_vector_search("dense", query, limit, metadata_filter)
    return _documents_from_milvus_rows(rows, "dense")


def search_sparse(query: str, limit: int, metadata_filter: str) -> list[dict]:
    if not _sparse_uses_store():
        raise RuntimeError("sparse is not initialized")
    rows = _single_vector_search("sparse", query, limit, metadata_filter)
    return _documents_from_milvus_rows(rows, "sparse")


def search_hybrid(
    query: str,
    limit: int,
    metadata_filter: str,
    dense_weight: float,
    sparse_weight: float,
) -> list[dict]:
    if not _sparse_uses_store():
        raise RuntimeError("sparse is not initialized")
    rows = _hybrid_search(query, limit, metadata_filter, dense_weight, sparse_weight)
    return _documents_from_milvus_rows(rows, "hybrid")


def _single_vector_search(mode: SearchMode, query: str, limit: int, metadata_filter: str):
    _require_search_ready()
    return get_milvus_client().search(
        QDRANT_CHUNKS_COLLECTION,
        data=[_query_data_for_mode(mode, query)],
        anns_field=_vector_field_for_mode(mode),
        search_params=_search_params_for_mode(mode),
        limit=limit,
        filter=metadata_filter,
        output_fields=["*"],
        timeout=_timeout,
    )


def _hybrid_search(
    query: str,
    limit: int,
    metadata_filter: str,
    dense_weight: float,
    sparse_weight: float,
):
    from pymilvus import AnnSearchRequest, WeightedRanker

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
    return get_milvus_client().hybrid_search(
        QDRANT_CHUNKS_COLLECTION,
        reqs=reqs,
        ranker=WeightedRanker(
            float(dense_weight),
            float(sparse_weight),
        ),
        limit=limit,
        output_fields=["*"],
        timeout=_timeout,
    )


def add_file_chunks(chunks: list[dict], file_id: str) -> int:
    if not chunks:
        return 0
    if not file_id:
        raise ValueError("file_id is required")
    _require_search_ready()
    delete_file_chunks(file_id)
    get_milvus_client().insert(
        collection_name=QDRANT_CHUNKS_COLLECTION,
        data=_to_file_rows(chunks, file_id),
        timeout=_timeout,
    )
    return len(chunks)


def delete_file_chunks(file_id: str) -> int:
    return _delete_by_filter(_file_payload_filter([file_id]))


def get_total_chunks(file_ids: list[str] | None = None) -> int:
    return len(get_search_documents(build_file_filter(file_ids)))


def get_search_documents(metadata_filter: str) -> list[dict]:
    rows = get_milvus_client().query(
        collection_name=QDRANT_CHUNKS_COLLECTION,
        filter=metadata_filter,
        output_fields=["*"],
        timeout=_timeout,
    )
    results = []
    for row in rows:
        metadata = _metadata_from_row(row)
        results.append({
            "id": str(row.get("pk") or metadata.get("id", "")),
            "content": row.get("text") or "",
            "metadata": metadata,
        })
    return results


def build_file_filter(file_ids: list[str] | None = None) -> str:
    if file_ids is None:
        return ""
    if not file_ids:
        raise ValueError("file_ids cannot be empty")
    return _file_payload_filter(file_ids)


def _to_file_rows(chunks: list[dict], file_id: str) -> list[dict]:
    dense_vectors = _get_dense().embed_documents([chunk["content"] for chunk in chunks])
    sparse_vectors = _sparse_vectors_for_documents([chunk["content"] for chunk in chunks])
    rows = []
    for chunk, dense_vector, sparse_vector in zip(chunks, dense_vectors, sparse_vectors):
        metadata = dict(chunk.get("metadata") or {})
        if "chunk_index" not in metadata:
            raise ValueError("chunk metadata.chunk_index is required")
        if not metadata.get("filename"):
            raise ValueError("chunk metadata.filename is required")
        row = {
            "pk": _point_id(chunk["id"]),
            "text": chunk["content"],
            "file_id": file_id,
            "chunk_index": int(metadata["chunk_index"]),
            "filename": metadata["filename"],
            _dense_vector_field(): dense_vector,
        }
        if metadata.get("s3_url"):
            row["s3_url"] = metadata["s3_url"]
        if metadata.get("created_at"):
            row["created_at"] = metadata["created_at"]
        if sparse_vector is not None:
            row["sparse"] = sparse_vector
        rows.append(row)
    return rows


def _sparse_vectors_for_documents(contents: list[str]) -> list[dict[int, float] | None]:
    if not _sparse_uses_store() or _sparse_is_builtin_bm25():
        return [None] * len(contents)
    sparse = _get_sparse()
    if sparse is None:
        raise RuntimeError("sparse is not initialized")
    return sparse.embed_documents(contents)


def _file_payload_filter(file_ids: list[str]) -> str:
    return f"file_id in {[str(file_id) for file_id in file_ids]!r}"


def _delete_by_filter(metadata_filter: str) -> int:
    rows = get_milvus_client().query(
        collection_name=QDRANT_CHUNKS_COLLECTION,
        filter=metadata_filter,
        output_fields=["pk"],
        timeout=_timeout,
    )
    ids = [row["pk"] for row in rows]
    if ids:
        get_milvus_client().delete(QDRANT_CHUNKS_COLLECTION, ids=ids, timeout=_timeout)
    return len(ids)


def _metadata_from_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"pk", "text", "vector", "dense", "sparse"}
    }


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
