from __future__ import annotations

from files.base import FilePage, FileRecord


def list_files_from_documents(documents: list[dict], limit: int = 50, cursor: str | None = None) -> FilePage:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    start = int(cursor) if cursor else 0
    records = _file_records(documents)
    page_records = records[start:start + limit]
    next_index = start + limit
    has_more = next_index < len(records)
    return FilePage(
        files=page_records,
        next_cursor=str(next_index) if has_more else None,
        has_more=has_more,
    )


def count_files_from_documents(documents: list[dict]) -> int:
    return len(_file_records(documents))


def _file_records(documents: list[dict]) -> list[FileRecord]:
    grouped: dict[str, dict] = {}
    for document in documents:
        metadata = dict(document.get("metadata") or {})
        file_id = metadata.get("file_id")
        if not file_id:
            continue
        item = grouped.setdefault(
            str(file_id),
            {
                "id": str(file_id),
                "filename": metadata.get("filename") or "",
                "chunk_count": 0,
                "created_at": metadata.get("created_at"),
            },
        )
        item["chunk_count"] += 1
        if not item["filename"] and metadata.get("filename"):
            item["filename"] = metadata["filename"]
        if metadata.get("created_at") and (not item["created_at"] or metadata["created_at"] < item["created_at"]):
            item["created_at"] = metadata["created_at"]
    records = [FileRecord(**item) for item in grouped.values()]
    return sorted(records, key=lambda record: (record.created_at or "", record.id), reverse=True)
