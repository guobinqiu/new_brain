from __future__ import annotations

import uuid
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from document_parser import parse_file


SUPPORTED_FILE_EXTENSIONS = (".pdf", ".txt", ".md", ".markdown", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp")


def create_file_id() -> str:
    return str(uuid.uuid4())


def index_file(application, file_id: str, path: str | Path, filename: str, extra_metadata: dict | None = None) -> int:
    chunks = parse_file(str(path), original_filename=filename, ocr=application.ocr)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for chunk in chunks:
        chunk_metadata = chunk.setdefault("metadata", {})
        if extra_metadata:
            chunk_metadata.update(extra_metadata)
        chunk_metadata.setdefault("created_at", created_at)
    count = application.store.add_file_chunks(chunks, file_id=file_id)
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
