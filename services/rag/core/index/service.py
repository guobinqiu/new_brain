from __future__ import annotations

import uuid
import hashlib
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from services.rag.core.index.chunking import parser_blocks_to_chunks
from shared.config import ChunkingConfig, StorageConfig
from shared.deadline import request_timeout
from services.rag.core.index.errors import index_stage
from services.rag.core.scope import current_app_id


SUPPORTED_FILE_EXTENSIONS = (".pdf", ".txt", ".md", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
STABLE_CHUNK_NAMESPACE = uuid.UUID("a7c76a79-33f4-4df8-b6f8-f77553a89c11")
logger = logging.getLogger("services.rag")


def create_file_id() -> str:
    return str(uuid.uuid4())


def stable_chunk_id(app_id: str, file_id: str, chunk_index: int) -> str:
    if chunk_index < 0:
        raise ValueError("chunk_index must be greater than or equal to 0")
    file_prefix = hashlib.blake2b(f"{app_id}:{file_id}".encode("utf-8"), digest_size=12).digest()
    raw = bytearray(file_prefix + chunk_index.to_bytes(4, "big"))
    raw[6] = (raw[6] & 0x0F) | 0x50
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def index_file(state, file_id: str, path: str | Path, filename: str, extra_metadata: dict | None = None) -> int:
    with index_stage("parse", "parser"):
        blocks = state.parser_client.parse_file(str(path), original_filename=filename)
    config = getattr(getattr(state, "config", None), "chunking", ChunkingConfig())
    with index_stage("chunk", "index"):
        chunks = parser_blocks_to_chunks(blocks, filename, config)
        chunks = prepare_index_chunks(chunks, app_id=current_app_id(), file_id=file_id, filename=filename, extra_metadata=extra_metadata)
    with index_stage("vector_write", "vector"):
        return state.vector_client.add_file_chunks(chunks, file_id=file_id)


def prepare_index_chunks(chunks: list[dict], *, app_id: str, file_id: str, filename: str, extra_metadata: dict | None = None) -> list[dict]:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prepared = []
    for chunk_index, chunk in enumerate(chunks):
        chunk_metadata = dict(chunk.get("metadata") or {})
        if extra_metadata:
            chunk_metadata.update(extra_metadata)
        chunk_metadata["filename"] = filename
        chunk_metadata["chunk_index"] = chunk_index
        chunk_metadata.setdefault("created_at", created_at)
        prepared.append({
            "id": stable_chunk_id(app_id, file_id, chunk_index),
            "content": chunk["content"],
            "metadata": chunk_metadata,
        })
    return prepared


def index_presigned_file(state, file_id: str, presigned_url: str, s3_url: str, filename: str | None = None) -> tuple[int, int]:
    """返回 ``(chunk_count, file_size)``。"""
    resolved_filename = filename or filename_from_s3_url(s3_url)
    ext = Path(resolved_filename).suffix.lower()
    validate_supported_file_extension(ext)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / f"download{ext}"
        with index_stage("download", "download"):
            download_presigned_file(presigned_url, path, state.config.storage)
        file_size = path.stat().st_size
        count = index_file(state, file_id, path, resolved_filename, extra_metadata={"s3_url": s3_url})
        return count, file_size


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


def download_presigned_file(presigned_url: str, path: str | Path, storage: StorageConfig) -> None:
    response = httpx.get(presigned_url, timeout=request_timeout(storage.download_timeout))
    response.raise_for_status()
    Path(path).write_bytes(response.content)
