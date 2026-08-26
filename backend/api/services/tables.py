from fastapi import HTTPException

from api.schemas import AdminTablePartsRequest, TablePartsRequest
from api.services.common import database_principal, require_ready, scoped_store


def client_table_parts(req: TablePartsRequest, principal):
    return _table_parts(req, principal)


def table_parts(req: AdminTablePartsRequest, principal):
    return _table_parts(req, principal)


def _table_parts(req: TablePartsRequest | AdminTablePartsRequest, principal):
    require_ready()
    table_principal = database_principal(principal, getattr(req, "app_id", None))
    store = scoped_store(table_principal)
    documents = store.get_search_documents(store.build_file_filter([req.file_id]))
    parts = [
        _table_part(document)
        for document in documents
        if _is_requested_table(document, req.table_id)
    ]
    if not parts:
        raise HTTPException(status_code=404, detail="table not found")
    return {
        "file_id": req.file_id,
        "table_id": req.table_id,
        "parts": sorted(parts, key=_table_part_sort_key),
    }


def _is_requested_table(document: dict, table_id: str) -> bool:
    metadata = document.get("metadata") or {}
    return metadata.get("content_type") == "table" and metadata.get("table_id") == table_id


def _table_part(document: dict) -> dict:
    metadata = document.get("metadata") or {}
    return {
        "table_part_index": metadata.get("table_part_index"),
        "table_part_count": metadata.get("table_part_count"),
        "chunk_index": metadata.get("chunk_index"),
        "content": document.get("content"),
    }


def _table_part_sort_key(part: dict):
    table_part_index = part.get("table_part_index")
    chunk_index = part.get("chunk_index")
    return (
        table_part_index if isinstance(table_part_index, int) else 10**12,
        chunk_index if isinstance(chunk_index, int) else 10**12,
    )
