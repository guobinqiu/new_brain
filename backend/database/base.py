from __future__ import annotations

from dataclasses import dataclass

from typing import Protocol


@dataclass(frozen=True)
class FileRecord:
    id: str
    filename: str
    chunk_count: int
    created_at: str | None = None
    s3_url: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class FilePage:
    files: list[FileRecord]
    next_cursor: str | None
    has_more: bool
    prev_cursor: str | None = None


class Database(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def ready(self) -> bool: ...

    def upsert_file(self, app_id: str, file_id: str, filename: str, s3_url: str, *, size: int | None = None, chunk_count: int = 0) -> None: ...
    def soft_delete_file(self, app_id: str, file_id: str) -> int: ...
    def list_files(self, app_id: str, limit: int = 50, cursor: str | None = None, direction: str = "next") -> FilePage: ...
    def purge_app(self, app_id: str) -> int: ...


class FakeDatabase:
    """内存实现，供测试注入 application.database，避免 e2e 依赖真实 PG。

    分页语义与 PostgresDatabase 完全一致：列表按 (created_at, id) DESC（新→旧）；
    next = id < cursor；prev = id > cursor 取回反转。
    """

    def __init__(self):
        self._rows: dict[tuple[str, str], dict] = {}
        self._next_id = 1
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

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
                "deleted_at": None,
            }
            self._next_id += 1
            self._rows[key] = row
        else:
            row.update(filename=filename, s3_url=s3_url, size=size, chunk_count=chunk_count, deleted_at=None)

    def soft_delete_file(self, app_id, file_id) -> int:
        row = self._rows.get((app_id, file_id))
        if row is None or row["deleted_at"] is not None:
            return 0
        row["deleted_at"] = "2026-08-20T00:00:00+00:00"
        return 1

    def list_files(self, app_id, limit=50, cursor=None, direction="next") -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        rows = [r for r in self._rows.values() if r["app_id"] == app_id and r["deleted_at"] is None]
        rows.sort(key=lambda r: (r["created_at"], int(r["id"])), reverse=True)  # 新→旧
        cursor_id = int(cursor) if cursor is not None else None
        if direction == "prev":
            if cursor_id is None:
                raise ValueError("cursor is required for prev direction")
            raw = [r for r in rows if int(r["id"]) > cursor_id]
            raw.sort(key=lambda r: (r["created_at"], int(r["id"])))  # 旧→新
            raw = raw[: limit + 1]
            page_rows = list(reversed(raw[:limit]))  # 本页 = 掐掉探针行（raw[limit]）后反转
            prev_cursor = str(page_rows[0]["id"]) if len(raw) > limit else None
            last_id = int(page_rows[-1]["id"]) if page_rows else None
            has_more = last_id is not None and any(int(r["id"]) < last_id for r in rows)
            next_cursor = str(last_id) if has_more else None
        else:
            if cursor_id is not None:
                rows = [r for r in rows if int(r["id"]) < cursor_id]
            page_rows = rows[: limit + 1]
            has_more = len(page_rows) > limit
            page_rows = page_rows[:limit]
            prev_cursor = str(page_rows[0]["id"]) if cursor_id is not None and page_rows else None
            next_cursor = str(page_rows[-1]["id"]) if has_more else None
        return FilePage(
            files=[
                FileRecord(
                    id=r["file_id"],
                    filename=r["filename"],
                    chunk_count=r["chunk_count"],
                    created_at=r["created_at"],
                    s3_url=r["s3_url"],
                    size=r["size"],
                )
                for r in page_rows
            ],
            prev_cursor=prev_cursor,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def purge_app(self, app_id) -> int:
        keys = [k for k in self._rows if k[0] == app_id]
        for k in keys:
            del self._rows[k]
        return len(keys)