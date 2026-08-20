from __future__ import annotations

from dataclasses import dataclass

from typing import Protocol


@dataclass(frozen=True)
class FileRecord:
    id: str
    filename: str
    chunk_count: int
    created_at: str | None = None
    indexed_at: str | None = None
    s3_url: str | None = None
    size: int | None = None
    status: str = "success"
    error: str | None = None


@dataclass(frozen=True)
class FilePage:
    files: list[FileRecord]
    next_cursor: str | None
    has_more: bool
    total: int = 0


class Database(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def ready(self) -> bool: ...

    def create_file(self, app_id: str, file_id: str, filename: str, s3_url: str, *, size: int | None = None) -> None: ...
    def mark_file_indexing(self, app_id: str, file_id: str) -> None: ...
    def mark_file_failed(self, app_id: str, file_id: str, error: str) -> None: ...
    def upsert_file(self, app_id: str, file_id: str, filename: str, s3_url: str, *, size: int | None = None, chunk_count: int = 0) -> None: ...
    def soft_delete_file(self, app_id: str, file_id: str) -> int: ...
    def list_files(self, app_id: str, limit: int = 50, cursor: str | None = None) -> FilePage: ...
    def purge_app(self, app_id: str) -> int: ...


class FakeDatabase:
    """内存实现，供测试注入 application.database，避免 e2e 依赖真实 PG。

    分页语义与 PostgresDatabase 完全一致：列表按 (created_at, id) DESC（新→旧）；
    next = id < cursor。
    """

    def __init__(self):
        self._rows: dict[tuple[str, str], dict] = {}
        self._next_id = 1
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def create_file(self, app_id, file_id, filename, s3_url, *, size=None) -> None:
        key = (app_id, file_id)
        row = self._rows.get(key)
        if row is None:
            row = {
                "id": str(self._next_id),
                "app_id": app_id,
                "file_id": file_id,
                "filename": filename,
                "s3_url": s3_url,
                "size": size,
                "chunk_count": 0,
                "created_at": "2026-08-20T00:00:00+00:00",
                "indexed_at": None,
                "deleted_at": None,
                "status": "queued",
                "error": None,
            }
            self._next_id += 1
            self._rows[key] = row
        else:
            row.update(
                filename=filename,
                s3_url=s3_url,
                size=size,
                chunk_count=0,
                indexed_at=None,
                deleted_at=None,
                status="queued",
                error=None,
            )

    def mark_file_indexing(self, app_id, file_id) -> None:
        row = self._rows.get((app_id, file_id))
        if row is not None:
            row.update(status="indexing", error=None)

    def mark_file_failed(self, app_id, file_id, error) -> None:
        row = self._rows.get((app_id, file_id))
        if row is not None:
            row.update(status="failed", error=error, indexed_at=None)

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None:
        key = (app_id, file_id)
        row = self._rows.get(key)
        if row is None:
            row = {
                "id": str(self._next_id),
                "app_id": app_id,
                "file_id": file_id,
                "filename": filename,
                "s3_url": s3_url,
                "size": size,
                "chunk_count": chunk_count,
                "created_at": "2026-08-20T00:00:00+00:00",
                "indexed_at": "2026-08-20T00:00:00+00:00",
                "deleted_at": None,
                "status": "success",
                "error": None,
            }
            self._next_id += 1
            self._rows[key] = row
        else:
            row.update(
                filename=filename,
                s3_url=s3_url,
                size=size,
                chunk_count=chunk_count,
                indexed_at="2026-08-20T00:00:00+00:00",
                deleted_at=None,
                status="success",
                error=None,
            )

    def soft_delete_file(self, app_id, file_id) -> int:
        row = self._rows.get((app_id, file_id))
        if row is None or row["deleted_at"] is not None:
            return 0
        row["deleted_at"] = "2026-08-20T00:00:00+00:00"
        return 1

    def list_files(self, app_id, limit=50, cursor=None) -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        rows = [r for r in self._rows.values() if r["app_id"] == app_id and r["deleted_at"] is None]
        rows.sort(key=lambda r: (r["created_at"], int(r["id"])), reverse=True)  # 新→旧
        cursor_id = int(cursor) if cursor is not None else None
        if cursor_id is not None:
            rows = [r for r in rows if int(r["id"]) < cursor_id]
        page_rows = rows[: limit + 1]
        has_more = len(page_rows) > limit
        page_rows = page_rows[:limit]
        next_cursor = str(page_rows[-1]["id"]) if has_more else None
        total = len(rows) if cursor_id is None else len([r for r in self._rows.values() if r["app_id"] == app_id and r["deleted_at"] is None])
        return FilePage(
            files=[
                FileRecord(
                    id=r["file_id"],
                    filename=r["filename"],
                    chunk_count=r["chunk_count"],
                    created_at=r["created_at"],
                    indexed_at=r["indexed_at"],
                    s3_url=r["s3_url"],
                    size=r["size"],
                    status=r["status"],
                    error=r["error"],
                )
                for r in page_rows
            ],
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
        )

    def purge_app(self, app_id) -> int:
        keys = [k for k in self._rows if k[0] == app_id]
        for k in keys:
            del self._rows[k]
        return len(keys)
