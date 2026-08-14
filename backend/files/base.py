from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class FileRecord:
    id: str
    filename: str
    chunk_count: int


@dataclass(frozen=True)
class FilePage:
    files: list[FileRecord]
    next_cursor: str | None
    has_more: bool
