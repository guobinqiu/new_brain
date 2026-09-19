import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile
from minio import Minio
from shared.config import StorageConfig

from services.rag.core.api.schemas import ChunksQueryRequest, FileIndexRequest, PresignRequest, StoredFileIndexRequest
from services.rag.core.api.services.common import database_principal, iso_datetime, require_app_database, require_ready, scoped_vector, vector_scope
from services.rag.core.auth import Principal
from services.rag.core.auth import validate_app_id
from services.rag.core.index import create_file_id, index_presigned_file
from services.rag.core.index.service import SUPPORTED_FILE_EXTENSIONS, filename_from_s3_url, parse_s3_url, validate_supported_file_extension
from shared.config import RetryConfig
from shared.retry import retry_call
from shared.upstream import UpstreamServiceError
from shared.tracing import get_trace_id
from services.rag.core.index.errors import index_stage, index_error_detail
from services.rag.core.presign import fetch_presigned_url


logger = logging.getLogger("services.rag")


async def upload_file(state, file: UploadFile, app_id: str, principal: Principal, *, file_id: str | None = None):
    effective_principal = database_principal(principal, app_id)
    _require_storage(state.config.storage)
    require_app_database(state, effective_principal)
    if not file.filename:
        raise HTTPException(400, "No filename")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_FILE_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    try:
        version = None
        if file_id is not None:
            if state.db_client is None:
                raise HTTPException(503, "file updates require a metadata database")
            record = state.db_client.get_file(effective_principal.app_id, file_id)
            if record is None:
                raise HTTPException(404, "file not found")
            if record.status in {"queued", "indexing"}:
                raise HTTPException(409, "file is being indexed")
            version = create_file_id()
        else:
            file_id = create_file_id()
        length = _upload_file_size(file)
        s3_url = upload_file_to_storage(state.config.storage, effective_principal.app_id, file_id, file.filename, file.file, length, file.content_type or "application/octet-stream", version=version)
        return {"file_id": file_id, "s3_url": s3_url, "filename": file.filename}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Upload failed", extra={"event": "upload_failed", "document_filename": file.filename})
        raise HTTPException(500, str(e))


def client_index_file(state, req: FileIndexRequest, principal: Principal):
    return _index_file(state, req, principal)


def index_file(state, req: FileIndexRequest | StoredFileIndexRequest, principal: Principal):
    if isinstance(req, StoredFileIndexRequest):
        return retry_file(state, req.file_id, req.app_id, principal)
    return _index_file(state, req, principal)


def _index_file(state, req: FileIndexRequest, principal: Principal):
    file_id = req.file_id or create_file_id()
    effective_principal = None
    metadata_started = False
    try:
        require_ready(state)
        filename = req.filename or filename_from_s3_url(req.s3_url)
        validate_supported_file_extension(Path(filename).suffix.lower())
        effective_principal = database_principal(principal, req.app_id)
        if state.db_client is not None:
            with index_stage("collection_check", "vector"):
                require_app_database(state, effective_principal)
            with index_stage("metadata_create", "database"):
                _metadata_write(state, lambda: state.db_client.create_file(effective_principal.app_id, file_id, filename, req.s3_url), "metadata_create")
            metadata_started = True
            with index_stage("metadata_indexing", "database"):
                _metadata_write(state, lambda: state.db_client.mark_file_indexing(effective_principal.app_id, file_id), "metadata_indexing")
        with vector_scope(state, effective_principal):
            if state.db_client is None:
                with index_stage("collection_initialize", "vector"):
                    state.vector_client.ensure_app_collection(effective_principal.app_id)
            presigned_url = _resolve_presigned_url(state, effective_principal.app_id, file_id, req.s3_url, filename, req.presigned_url)
            count, file_size = index_presigned_file(
                state,
                file_id=file_id,
                presigned_url=presigned_url,
                s3_url=req.s3_url,
                filename=filename,
            )
        if state.db_client is not None:
            with index_stage("metadata_success", "database"):
                _metadata_write(
                    state,
                    lambda: state.db_client.upsert_file(
                        effective_principal.app_id,
                        file_id,
                        filename,
                        req.s3_url,
                        size=file_size,
                        chunk_count=count,
                    ),
                    "metadata_success",
                )
        logger.info("File indexed", extra={"event": "file_indexed", "document_filename": filename, "file_id": file_id, "trace_id": get_trace_id(), "chunk_count": count})
        return {"success": True, "error": None, "service": None, "retryable": False, "traceId": get_trace_id(), "file_id": file_id}
    except Exception as exc:
        if isinstance(exc, UpstreamServiceError):
            error = exc
        elif isinstance(exc, HTTPException):
            error = UpstreamServiceError(
                service="rag", error=str(exc.detail),
                retryable=False, status_code=exc.status_code,
            )
        elif isinstance(exc, ValueError):
            error = UpstreamServiceError(
                service="rag", error=str(exc),
                retryable=False, status_code=400,
            )
        else:
            error = UpstreamServiceError(
                service="rag", error=str(exc) or None,
                retryable=False, status_code=500,
            )
        if metadata_started:
            _mark_file_failed_if_possible(state, effective_principal, file_id, json.dumps(error.detail()))
        logger.exception("File index failed", extra={
            "event": "file_index_failed", "file_id": file_id, "trace_id": get_trace_id(),
            "retryable": error.retryable, "error_type": type(exc).__name__,
        })
        raise HTTPException(error.status_code, index_error_detail(error, file_id)) from exc


def presign_object(state, req: PresignRequest, _=None):
    bucket, object_name = parse_storage_url(req.s3_url)
    client = minio_client(state.config.storage)
    try:
        url = client.presigned_get_object(bucket, object_name, expires=timedelta(seconds=req.expires_in))
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return {"presigned_url": url}


def client_presign_object(state, req: PresignRequest, principal: Principal):
    bucket, object_name = parse_storage_url(req.s3_url)
    if bucket != state.config.storage.bucket or not object_name.startswith(storage_prefix(principal.app_id)):
        raise HTTPException(403, "file does not belong to this app")
    return presign_object(state, req, principal)


def retry_file(state, file_id: str, app_id: str | None, principal: Principal):
    claimed = False
    effective_principal = None
    try:
        require_ready(state)
        effective_principal = database_principal(principal, app_id)
        if state.db_client is None:
            raise HTTPException(503, "file retry is unavailable without a metadata database")
        record = state.db_client.get_file(effective_principal.app_id, file_id)
        if record is None:
            raise HTTPException(404, "file not found")
        claimed = state.db_client.claim_file_retry(effective_principal.app_id, file_id)
        if not claimed:
            raise HTTPException(409, "only failed files can be retried")
        return _index_file(state, FileIndexRequest(
            app_id=effective_principal.app_id, file_id=file_id,
            filename=record.filename, s3_url=record.s3_url,
        ), principal)
    except Exception as exc:
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            detail, status = exc.detail, exc.status_code
        else:
            error = exc if isinstance(exc, UpstreamServiceError) else UpstreamServiceError(
                service="rag", error=str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
                retryable=False, status_code=exc.status_code if isinstance(exc, HTTPException) else 500,
            )
            detail, status = index_error_detail(error, file_id), error.status_code
        if claimed:
            stored_error = {key: detail.get(key) for key in ("error", "service", "retryable", "traceId")}
            _mark_file_failed_if_possible(state, effective_principal, file_id, json.dumps(stored_error))
        logger.exception("File retry failed", extra={"file_id": file_id, "trace_id": get_trace_id()})
        raise HTTPException(status, detail) from exc


def _resolve_presigned_url(state, app_id: str, file_id: str, s3_url: str, filename: str, presigned_url: str | None) -> str:
    if presigned_url:
        return presigned_url
    if state.db_client is None:
        raise HTTPException(400, "presigned_url is required when metadata database is disabled")
    with index_stage("presign", "presign"):
        template = state.db_client.get_presign_config(app_id)
        if not template:
            raise HTTPException(400, "app presign_config is not configured")
        return fetch_presigned_url(template, {
            "app_id": app_id, "file_id": file_id,
            "s3_url": s3_url, "filename": filename,
        }, timeout=state.config.storage.presign_timeout)


def files(state, limit: int = 50, cursor: str | None = None, app_id: str | None = None, principal: Principal | None = None):
    require_ready(state)
    try:
        effective_principal = database_principal(principal, app_id)
        page = _list_indexed_files(state, effective_principal, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "files": page["files"],
        "next_cursor": page["next_cursor"],
        "has_more": page["has_more"],
        "total": page["total"],
    }


def chunks(state, req: ChunksQueryRequest, principal: Principal):
    require_ready(state)
    try:
        vector = scoped_vector(state, database_principal(principal, req.app_id))
        page = vector.list_chunks(file_ids=req.file_ids, limit=req.limit, cursor=req.cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "chunks": [chunk_record(document) for document in page["documents"]],
        "next_cursor": page["next_cursor"],
        "has_more": page["has_more"],
    }


def dense_vector(state, app_id: str, chunk_id: str, principal: Principal):
    return _chunk_vector(state, app_id, chunk_id, principal, vector_type="dense")


def _chunk_vector(state, app_id: str, chunk_id: str, principal: Principal, *, vector_type: str):
    require_ready(state)
    effective_principal = database_principal(principal, app_id)
    vector = state.vector_client
    method_name = f"get_{vector_type}_vector"
    method = getattr(vector, method_name, None)
    if not callable(method):
        raise HTTPException(status_code=400, detail=f"{vector_type} vector is not supported by current vector")
    try:
        with vector_scope(state, effective_principal):
            vector = method(chunk_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if vector is None:
        raise HTTPException(status_code=404, detail="chunk not found")
    return {"chunk_id": chunk_id, "type": vector_type, "vector": vector}


def client_delete_file(state, file_id: str, principal: Principal):
    return delete_index_file(state, file_id, principal)


def delete_file(state, file_id: str, app_id: str | None, principal: Principal):
    effective_principal = database_principal(principal, app_id)
    _require_storage(state.config.storage)
    result = delete_index_file(state, file_id, effective_principal)
    try:
        delete_storage_file(state.config.storage, effective_principal.app_id, file_id)
    except Exception as exc:
        logger.warning(
            "Storage file delete failed",
            exc_info=True,
            extra={
                "event": "storage_file_delete_failed",
                "app_id": effective_principal.app_id,
                "file_id": file_id,
                "error": str(exc),
            },
        )
    logger.info(
        "File deleted",
        extra={
            "event": "file_deleted",
            "app_id": effective_principal.app_id,
            "file_id": file_id,
            "deleted_chunks": result["deleted_chunks"],
        },
    )
    return result


def delete_index_file(state, file_id: str, principal: Principal) -> dict[str, Any]:
    require_ready(state)
    vector = scoped_vector(state, principal)
    deleted_chunks = vector.delete_file_chunks(file_id)
    if state.db_client is not None:
        state.db_client.soft_delete_file(principal.app_id, file_id)
    return {"deleted_chunks": deleted_chunks}


def _list_indexed_files(state, principal: Principal, *, limit: int, cursor: str | None) -> dict[str, Any]:
    if state.db_client is None:
        raise HTTPException(503, "file listing is unavailable without a metadata database")
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    page = state.db_client.list_files(principal.app_id, limit=limit, cursor=cursor)
    return {
        "files": [_file_record(row) for row in page.files],
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
        "total": page.total,
    }


def _file_record(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename": record.filename,
        "chunk_count": record.chunk_count,
        "created_at": iso_datetime(record.created_at),
        "indexed_at": iso_datetime(record.indexed_at),
        "s3_url": record.s3_url,
        "size": record.size,
        "status": record.status,
        "error": _file_error(record.error),
    }


def _file_error(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        error = json.loads(value)
    except ValueError:
        return None
    if not isinstance(error, dict) or type(error.get("retryable")) is not bool:
        return None
    return {"error": error.get("error"), "service": error.get("service"), "retryable": error["retryable"], "traceId": error.get("traceId")}


def _mark_file_failed_if_possible(state, principal: Principal, file_id: str, error: str) -> None:
    try:
        state.db_client.mark_file_failed(principal.app_id, file_id, error)
    except Exception:
        logger.error("Failed to record file indexing failure", extra={
            "app_id": principal.app_id, "file_id": file_id, "trace_id": get_trace_id(),
        })


def _metadata_write(state, operation, operation_name: str):
    retry = getattr(getattr(state, "config", None), "database", None)
    retry = getattr(retry, "retry", RetryConfig())
    return retry_call(operation, retry, should_retry=_retryable_database_error, operation_name=f"rag.{operation_name}")


def _retryable_database_error(exc: Exception) -> bool:
    module = type(exc).__module__
    name = type(exc).__name__
    return module.startswith(("psycopg", "psycopg_pool")) and name in {
        "OperationalError", "InterfaceError", "PoolTimeout", "ConnectionTimeout",
        "SerializationFailure", "DeadlockDetected",
    }


def chunk_record(document: dict) -> dict[str, Any]:
    metadata = dict(document.get("metadata") or {})
    return {
        "id": document.get("id"),
        "file_id": metadata.get("file_id"),
        "filename": metadata.get("filename"),
        "chunk_index": metadata.get("chunk_index"),
        "s3_url": metadata.get("s3_url"),
        "created_at": iso_datetime(metadata.get("created_at")),
        "content": document.get("content"),
    }


def parse_storage_url(s3_url: str) -> tuple[str, str]:
    try:
        return parse_s3_url(s3_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _require_storage(config: StorageConfig) -> None:
    if config.endpoint_url is None:
        raise HTTPException(503, "object storage is not configured")


def minio_client(config: StorageConfig) -> Minio:
    _require_storage(config)
    parsed = urlparse(config.endpoint_url)
    endpoint = parsed.netloc or parsed.path
    secure = parsed.scheme == "https"
    return Minio(
        endpoint,
        access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        secure=secure,
    )


def delete_storage_file(config: StorageConfig, app_id: str, file_id: str) -> int:
    bucket = config.bucket
    client = minio_client(config)
    if not client.bucket_exists(bucket):
        return 0
    prefix = storage_file_prefix(app_id, file_id)
    deleted_count = 0
    for item in client.list_objects(bucket, prefix=prefix, recursive=True):
        client.remove_object(bucket, item.object_name)
        deleted_count += 1
    return deleted_count


def storage_prefix(app_id: str) -> str:
    validate_app_id(app_id)
    return f"uploads/{app_id}/"


def storage_file_prefix(app_id: str, file_id: str) -> str:
    return f"{storage_prefix(app_id)}{file_id}/"


def upload_file_to_storage(config: StorageConfig, app_id: str, file_id: str, filename: str, data, length: int, content_type: str, *, version: str | None = None) -> str:
    bucket = config.bucket
    prefix = storage_file_prefix(app_id, file_id)
    if version is not None:
        prefix += f"{version}/"
    object_name = f"{prefix}{Path(filename).name}"
    client = minio_client(config)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(
        bucket,
        object_name,
        data,
        length=length,
        content_type=content_type,
    )
    return f"s3://{bucket}/{object_name}"


def _upload_file_size(file: UploadFile) -> int:
    stream = file.file
    current = stream.tell()
    stream.seek(0, os.SEEK_END)
    length = stream.tell()
    stream.seek(0)
    if current not in (0, length):
        stream.seek(0)
    return length
