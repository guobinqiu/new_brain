from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.rag.core.auth import AppCredential


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


class DbClient(Protocol):
    def initialize(self) -> None:
        ...

    def ping(self) -> bool:
        ...

    def close(self) -> None:
        ...

    def create_app(self, app_id: str) -> AppCredential:
        ...

    def get_app(self, app_id: str) -> AppCredential | None:
        ...

    def get_presign_config(self, app_id: str) -> str | None:
        ...

    def set_presign_config(self, app_id: str, template: str) -> bool:
        ...

    def get_file(self, app_id: str, file_id: str) -> FileRecord | None:
        ...

    def claim_file_retry(self, app_id: str, file_id: str) -> bool:
        ...

    def get_app_by_api_key(self, api_key: str) -> AppCredential | None:
        ...

    def list_apps(self) -> list[AppCredential]:
        ...

    def delete_app(self, app_id: str) -> bool:
        ...

    def create_file(self, app_id, file_id, filename, s3_url, *, size=None) -> None:
        ...

    def mark_file_indexing(self, app_id, file_id) -> None:
        ...

    def mark_file_failed(self, app_id, file_id, error) -> None:
        ...

    def mark_interrupted_indexing_failed(self) -> int:
        ...

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None:
        ...

    def soft_delete_file(self, app_id, file_id) -> int:
        ...

    def purge_app(self, app_id) -> int:
        ...

    def list_files(self, app_id, limit=50, cursor=None) -> FilePage:
        ...
