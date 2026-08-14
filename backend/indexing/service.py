from __future__ import annotations

import uuid
from pathlib import Path

from document_parser import parse_file


def create_file_id() -> str:
    return uuid.uuid4().hex


def index_file(application, file_id: str, path: str | Path, filename: str, extra_metadata: dict | None = None) -> int:
    chunks = parse_file(str(path), original_filename=filename, ocr=application.ocr)
    if extra_metadata:
        for chunk in chunks:
            chunk_metadata = chunk.setdefault("metadata", {})
            chunk_metadata.update(extra_metadata)
    count = application.store.add_file_chunks(chunks, file_id=file_id)
    return count
