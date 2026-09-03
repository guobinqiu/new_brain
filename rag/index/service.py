from __future__ import annotations

import uuid
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx


SUPPORTED_FILE_EXTENSIONS = (".pdf", ".txt", ".md", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".webp", ".bmp")


def create_file_id() -> str:
    return str(uuid.uuid4())


def index_file(application, file_id: str, path: str | Path, filename: str, extra_metadata: dict | None = None) -> int:
    chunks = application.parser.parse_file(str(path), original_filename=filename, ocr=application.ocr)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for chunk in chunks:
        chunk_metadata = chunk.setdefault("metadata", {})
        if extra_metadata:
            chunk_metadata.update(extra_metadata)
        chunk_metadata.setdefault("created_at", created_at)
    sparse = getattr(application, "sparse", None)
    if _uses_independent_sparse_index(application.store, sparse):
        sparse.delete_file_chunks(file_id)
        return _add_store_and_sparse_chunks(application.store, sparse, chunks, file_id)
    return application.store.add_file_chunks(chunks, file_id=file_id)


def _uses_independent_sparse_index(store, sparse) -> bool:
    if sparse is None:
        return False
    if not callable(getattr(sparse, "add_file_chunks", None)) or not callable(getattr(sparse, "delete_file_chunks", None)):
        return False
    sparse_uses_store = getattr(store, "sparse_uses_store", None)
    if callable(sparse_uses_store) and sparse_uses_store(sparse):
        return False
    return True


def _add_store_and_sparse_chunks(store, sparse, chunks: list[dict], file_id: str) -> int:
    store_context = copy_context()
    sparse_context = copy_context()
    with ThreadPoolExecutor(max_workers=2) as executor:
        store_future = executor.submit(store_context.run, store.add_file_chunks, chunks, file_id)
        sparse_future = executor.submit(sparse_context.run, sparse.add_file_chunks, chunks, file_id)
        count = store_future.result()
        sparse_future.result()
    return count


def index_presigned_object(application, file_id: str, presigned_url: str, s3_url: str, filename: str | None = None) -> tuple[int, int]:
    """返回 ``(chunk_count, file_size)``。"""
    resolved_filename = filename or filename_from_s3_url(s3_url)
    ext = Path(resolved_filename).suffix.lower()
    validate_supported_file_extension(ext)
    path = Path(download_presigned_file(presigned_url, ext))
    try:
        file_size = path.stat().st_size
        count = index_file(application, file_id, path, resolved_filename, extra_metadata={"s3_url": s3_url})
        return count, file_size
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def validate_supported_file_extension(ext: str) -> None:
    if ext not in SUPPORTED_FILE_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")


def filename_from_s3_url(s3_url: str) -> str:
    _, object_name = parse_s3_url(s3_url)
    filename = Path(object_name).name
    if not filename:
        raise ValueError("filename is required when s3_url has no object name")
    return filename


def parse_s3_url(s3_url: str) -> tuple[str, str]:
    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    object_name = parsed.path.lstrip("/")
    if not bucket or not object_name:
        raise ValueError("s3_url must include bucket and object key")
    return bucket, object_name


def download_presigned_file(presigned_url: str, suffix: str) -> str:
    response = httpx.get(presigned_url, timeout=60)
    response.raise_for_status()
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(response.content)
        return handle.name
    finally:
        handle.close()
