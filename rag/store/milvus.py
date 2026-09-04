"""Milvus-backed document storage through native pymilvus client."""
from __future__ import annotations

import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from rag.dense.base import Dense
from rag.dense.huggingface import HuggingFaceDense
from rag.scope import app_collection, collection_name_for_app, current_collection
from rag.search.rank import weighted_reciprocal_rank
from rag.sparse.base import Sparse
from rag.store.startup import run_with_startup_retry


SearchMode = Literal["dense", "sparse", "hybrid"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DENSE_METRIC = "COSINE"


class MilvusStore:
    backend_name = "milvus"

    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        uri: str | None = None,
        timeout: int | None = None,
        parallel_sparse_embedding: bool = False,
    ):
        self.dense = dense or HuggingFaceDense()
        self.sparse = sparse
        self.uri = uri or "http://localhost:19530"
        self.timeout = timeout
        self.parallel_sparse_embedding = parallel_sparse_embedding
        self.client = None
        self.dense_vector_size: int | None = None
        self._document_locks: dict[str, threading.Lock] = {}
        self._document_locks_guard = threading.Lock()
        self._ready = False

    def start(self) -> None:
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
        if _is_lite_uri(self.uri):
            _release_lite_server(_connection_uri(self.uri))
        self._ready = False

    def drop_collections(self) -> None:
        collection_name = self._chunks_collection()
        client = self._client()
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)

    @property
    def ready(self) -> bool:
        return self._ready

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        if not chunks:
            return 0
        if not file_id:
            raise ValueError("file_id is required")
        self._require_ready()
        with self._document_lock(file_id):
            self.delete_file_chunks(file_id)
            self._client().insert(
                collection_name=self._chunks_collection(),
                data=self._to_file_rows(chunks, file_id),
                timeout=self.timeout,
            )
            self._client().flush(self._chunks_collection(), timeout=self.timeout)
        return len(chunks)

    def delete_file_chunks(self, file_id: str) -> int:
        return self._delete_by_filter(_file_payload_filter([file_id]))

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        rows = self._client().query(
            collection_name=self._chunks_collection(),
            filter=self.build_count_filter(file_ids),
            output_fields=["count(*)"],
            timeout=self.timeout,
        )
        if not rows:
            return 0
        return int(rows[0].get("count(*)") or 0)

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        metadata_filter = _combine_filters(self.build_file_filter(file_ids), _chunk_cursor_filter(cursor))
        rows = self._client().query(
            collection_name=self._chunks_collection(),
            filter=metadata_filter,
            output_fields=["*"],
            timeout=self.timeout,
            limit=limit + 1,
            order_by=_chunk_order_by(),
        )
        page_rows = rows[:limit]
        return {
            "documents": [_row_to_document(row) for row in page_rows],
            "next_cursor": _encode_chunk_cursor(page_rows[-1]) if len(rows) > limit and page_rows else None,
            "has_more": len(rows) > limit,
        }

    def get_dense_vector(self, chunk_id: str) -> list[float] | None:
        rows = self._query_chunk_vectors(chunk_id, [self._dense_vector_field()])
        if not rows:
            return None
        vector = rows[0].get(self._dense_vector_field())
        return list(vector) if vector is not None else None

    def get_sparse_vector(self, chunk_id: str) -> dict | None:
        if not self.sparse_uses_store():
            raise NotImplementedError("sparse vector is not supported by current store")
        rows = self._query_chunk_vectors(chunk_id, ["sparse"])
        if not rows:
            return None
        sparse = rows[0].get("sparse")
        if sparse is None:
            return None
        if isinstance(sparse, dict) and "indices" in sparse and "values" in sparse:
            return {"indices": list(sparse["indices"]), "values": list(sparse["values"])}
        return {"values": sparse}

    def supports_dense_vector(self) -> bool:
        return True

    def supports_sparse_vector(self, sparse: Sparse | None = None) -> bool:
        return self.sparse_uses_store(sparse)

    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        run_with_startup_retry(lambda: self.ensure_collections(collection_name))
        return collection_name

    def app_collection_exists(self, app_id: str) -> bool:
        return self._client().has_collection(collection_name_for_app(app_id))

    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        client = self._client()
        if not client.has_collection(collection_name):
            return False
        client.drop_collection(collection_name)
        return True

    def app_context(self, app_id: str):
        return app_collection(app_id)

    def get_search_documents(self, metadata_filter: str) -> list[dict]:
        query_kwargs = {
            "filter": metadata_filter,
            "output_fields": ["*"],
            "timeout": self.timeout,
        }
        if not metadata_filter:
            query_kwargs["limit"] = 16384
        rows = self._client().query(
            collection_name=self._chunks_collection(),
            **query_kwargs,
        )
        return [_row_to_document(row) for row in rows]

    def build_file_filter(self, file_ids: list[str] | None = None) -> str:
        if file_ids is None:
            return ""
        if not file_ids:
            raise ValueError("file_ids cannot be empty")
        return _file_payload_filter(file_ids)

    def build_count_filter(self, file_ids: list[str] | None = None) -> str:
        if file_ids is None:
            return 'pk != ""'
        return self.build_file_filter(file_ids)

    def encode_dense_query(self, query: str):
        return self.dense.embed_query(query)

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: str) -> list[dict]:
        rows = self._single_vector_search_with_data("dense", query_vector, limit, metadata_filter)
        return _documents_from_milvus_rows(rows, "dense")

    def search_dense(self, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return self.query_dense_vector(self.encode_dense_query(query), limit, metadata_filter)

    def encode_sparse_query(self, query: str):
        if not self.sparse_uses_store():
            raise RuntimeError("sparse is not initialized")
        return self._query_data_for_mode("sparse", query)

    def query_sparse_vector(self, query_vector, limit: int, metadata_filter: str) -> list[dict]:
        rows = self._single_vector_search_with_data("sparse", query_vector, limit, metadata_filter)
        return _documents_from_milvus_rows(rows, "sparse")

    def search_sparse(self, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return self.query_sparse_vector(self.encode_sparse_query(query), limit, metadata_filter)

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: str,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        if not self.sparse_uses_store():
            raise RuntimeError("sparse is not initialized")
        dense_items = self.search_dense(query, limit, metadata_filter)
        sparse_items = self.search_sparse(query, limit, metadata_filter)
        return weighted_reciprocal_rank(((dense_weight, dense_items), (sparse_weight, sparse_items)), limit, rrf_k)

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        from rag.sparse.milvus_bge_m3 import MilvusBGEM3Sparse
        from rag.sparse.milvus_bm25 import MilvusBM25Sparse

        return isinstance(self.sparse if sparse is None else sparse, (MilvusBGEM3Sparse, MilvusBM25Sparse))

    def ensure_collections(self, collection_name: str | None = None) -> None:
        client = self._client()
        target_collection = collection_name or self._chunks_collection()
        if not client.has_collection(target_collection):
            client.create_collection(
                collection_name=target_collection,
                schema=self._collection_schema(),
                index_params=self._collection_index_params(),
                timeout=self.timeout,
            )
        client.load_collection(target_collection, timeout=self.timeout)

    def _client(self):
        if self.client is None:
            from pymilvus import MilvusClient

            self.client = MilvusClient(uri=_connection_uri(self.uri), timeout=self.timeout)
        return self.client

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("search is not initialized")

    def _collection_schema(self):
        from pymilvus import DataType, Function, FunctionType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field(field_name="pk", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535, **self._text_field_kwargs())
        schema.add_field(field_name="file_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="filename", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=64, nullable=True)
        schema.add_field(field_name=self._dense_vector_field(), datatype=DataType.FLOAT_VECTOR, dim=self._dense_vector_size())
        if self.sparse_uses_store():
            schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
        if self._sparse_is_builtin_bm25():
            schema.add_function(Function(
                name="bm25_function",
                function_type=FunctionType.BM25,
                input_field_names="text",
                output_field_names="sparse",
            ))
        return schema

    def _text_field_kwargs(self) -> dict:
        if not self._sparse_is_builtin_bm25():
            return {}
        kwargs = {"enable_analyzer": True, "enable_match": True}
        analyzer_params = getattr(self.sparse, "analyzer_params", None)
        if analyzer_params is not None:
            kwargs["analyzer_params"] = analyzer_params
        return kwargs

    def _collection_index_params(self):
        from pymilvus import MilvusClient

        index_params = MilvusClient.prepare_index_params()
        for field_name, params in self._index_specs():
            index_params.add_index(field_name=field_name, **params)
        return index_params

    def _index_specs(self) -> list[tuple[str, dict]]:
        specs = [(self._dense_vector_field(), self._dense_index_params())]
        if self.sparse_uses_store():
            specs.append(("sparse", self._sparse_index_params()))
        specs.append(("file_id", {"index_type": "INVERTED"}))
        specs.append(("chunk_index", {"index_type": "INVERTED"}))
        return specs

    def _vector_field_for_mode(self, mode: SearchMode):
        if not self.sparse_uses_store():
            return "vector"
        if mode == "dense":
            return "dense"
        if mode == "sparse":
            return "sparse"
        return ["dense", "sparse"]

    def _dense_vector_field(self) -> str:
        return "dense" if self.sparse_uses_store() else "vector"

    def _dense_vector_size(self) -> int:
        if self.dense_vector_size is None:
            raise RuntimeError("search is not initialized")
        return self.dense_vector_size

    def _search_params_for_mode(self, mode: SearchMode):
        if mode == "dense":
            return {"metric_type": DENSE_METRIC, "params": {}}
        sparse_params = self._sparse_search_params()
        if mode == "sparse":
            return sparse_params
        return [
            {"metric_type": DENSE_METRIC, "params": {}},
            sparse_params,
        ]

    def _sparse_search_params(self):
        if self._sparse_is_builtin_bm25():
            return {"metric_type": "BM25", "params": {}}
        return {"metric_type": "IP", "params": {}}

    def _index_params_for_mode(self, mode: SearchMode):
        dense_index = self._dense_index_params()
        if not self.sparse_uses_store() or mode == "dense":
            return dense_index
        sparse_index = self._sparse_index_params()
        if mode == "sparse":
            return sparse_index
        return [dense_index, sparse_index]

    def _dense_index_params(self) -> dict:
        if _is_lite_uri(self.uri):
            return {"metric_type": DENSE_METRIC, "index_type": "FLAT", "params": {}}
        return {"metric_type": DENSE_METRIC, "index_type": "AUTOINDEX", "params": {}}

    def _sparse_index_params(self):
        if self._sparse_is_builtin_bm25():
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

    def _query_data_for_mode(self, mode: SearchMode, query: str):
        if mode == "dense":
            return self.dense.embed_query(query)
        if self._sparse_is_builtin_bm25():
            return query
        if self.sparse is None:
            raise RuntimeError("sparse is not initialized")
        return self.sparse.embed_query(query)

    def _sparse_is_builtin_bm25(self) -> bool:
        from rag.sparse.milvus_bm25 import MilvusBM25Sparse

        return isinstance(self.sparse, MilvusBM25Sparse)

    def _single_vector_search(self, mode: SearchMode, query: str, limit: int, metadata_filter: str):
        return self._single_vector_search_with_data(mode, self._query_data_for_mode(mode, query), limit, metadata_filter)

    def _single_vector_search_with_data(self, mode: SearchMode, query_data, limit: int, metadata_filter: str):
        self._require_ready()
        return self._client().search(
            self._chunks_collection(),
            data=[query_data],
            anns_field=self._vector_field_for_mode(mode),
            search_params=self._search_params_for_mode(mode),
            limit=limit,
            filter=metadata_filter,
            output_fields=["*"],
            timeout=self.timeout,
        )

    def _query_chunk_vectors(self, chunk_id: str, fields: list[str]) -> list[dict]:
        self._require_ready()
        return self._client().query(
            collection_name=self._chunks_collection(),
            filter=f'pk == "{chunk_id}"',
            output_fields=fields,
            timeout=self.timeout,
            limit=1,
        )

    def _to_file_rows(self, chunks: list[dict], file_id: str) -> list[dict]:
        contents = [chunk["content"] for chunk in chunks]
        dense_vectors, sparse_vectors = self._vectors_for_documents(contents)
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
                self._dense_vector_field(): dense_vector,
            }
            if metadata.get("s3_url"):
                row["s3_url"] = metadata["s3_url"]
            if metadata.get("created_at"):
                row["created_at"] = metadata["created_at"]
            if sparse_vector is not None:
                row["sparse"] = sparse_vector
            rows.append(row)
        return rows

    def _sparse_vectors_for_documents(self, contents: list[str]) -> list[dict[int, float] | None]:
        if not self.sparse_uses_store() or self._sparse_is_builtin_bm25():
            return [None] * len(contents)
        if self.sparse is None:
            raise RuntimeError("sparse is not initialized")
        return self.sparse.embed_documents(contents)

    def _vectors_for_documents(self, contents: list[str]) -> tuple[list[list[float]], list[dict[int, float] | None]]:
        if self.sparse_uses_store() and not self._sparse_is_builtin_bm25() and self.parallel_sparse_embedding:
            with ThreadPoolExecutor(max_workers=2) as executor:
                dense_future = executor.submit(self.dense.embed_documents, contents)
                sparse_future = executor.submit(self._sparse_vectors_for_documents, contents)
                return dense_future.result(), sparse_future.result()
        return self.dense.embed_documents(contents), self._sparse_vectors_for_documents(contents)

    def _delete_by_filter(self, metadata_filter: str) -> int:
        rows = self._client().query(
            collection_name=self._chunks_collection(),
            filter=metadata_filter,
            output_fields=["pk"],
            timeout=self.timeout,
        )
        ids = [row["pk"] for row in rows]
        if ids:
            self._client().delete(self._chunks_collection(), ids=ids, timeout=self.timeout)
            self._client().flush(self._chunks_collection(), timeout=self.timeout)
        return len(ids)

    def _chunks_collection(self) -> str:
        return current_collection()

    def _document_lock(self, file_id: str):
        with self._document_locks_guard:
            lock = self._document_locks.get(file_id)
            if lock is None:
                lock = threading.Lock()
                self._document_locks[file_id] = lock
            return lock


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
        return float(distance)
    return 1.0 / rank


def _chunk_order_by() -> list[str]:
    return [
        "file_id:asc",
        "chunk_index:asc",
        "pk:asc",
    ]


def _chunk_cursor_filter(cursor: str | None) -> str:
    if not cursor:
        return ""
    data = _decode_chunk_cursor(cursor)
    file_id = _milvus_string_literal(data["file_id"])
    chunk_index = int(data["chunk_index"])
    chunk_id = _milvus_string_literal(data["chunk_id"])
    return (
        f"(file_id > {file_id} or "
        f"(file_id == {file_id} and chunk_index > {chunk_index}) or "
        f"(file_id == {file_id} and chunk_index == {chunk_index} and pk > {chunk_id}))"
    )


def _combine_filters(*filters: str) -> str:
    active = [metadata_filter for metadata_filter in filters if metadata_filter]
    if len(active) == 1:
        return active[0]
    return " and ".join(f"({metadata_filter})" for metadata_filter in active)


def _encode_chunk_cursor(row: dict) -> str:
    payload = {
        "file_id": str(row["file_id"]),
        "chunk_index": int(row["chunk_index"]),
        "chunk_id": str(row["pk"]),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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


def _milvus_string_literal(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _row_to_document(row: dict) -> dict:
    metadata = _metadata_from_row(row)
    return {
        "id": str(row.get("pk") or metadata.get("id", "")),
        "content": row.get("text") or "",
        "metadata": metadata,
    }


def _file_payload_filter(file_ids: list[str]) -> str:
    return f"file_id in {[str(file_id) for file_id in file_ids]!r}"


def _metadata_from_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"pk", "text", "vector", "dense", "sparse"}
    }


def _point_id(chunk_id: str) -> str:
    return chunk_id
