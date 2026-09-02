import logging
import os
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from fastapi import HTTPException, UploadFile
from minio import Minio

from rag.api.runtime import runtime
from rag.api.schemas import AdminIndexJobRequest, ChunksQueryRequest, ObjectIndexRequest, PresignRequest
from rag.api.services.common import database_principal, iso_datetime, require_app_database, require_ready, scoped_store, store_context
from rag.auth import Principal
from rag.auth import validate_app_id
from rag.index import create_file_id, enqueue_index_job, index_presigned_object
from rag.index.queue import IndexQueueRejected
from rag.index.service import SUPPORTED_FILE_EXTENSIONS, parse_s3_url
from rag.index.workflow import create_index_job as run_create_index_job
from rag.index.workflow import index_object as run_index_object


logger = logging.getLogger("rag.app")


async def upload_file(file: UploadFile, app_id: str, principal: Principal):
    effective_principal = database_principal(principal, app_id)
    require_app_database(effective_principal)
    if not file.filename:
        raise HTTPException(400, "No filename")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_FILE_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    try:
        file_id = create_file_id()
        content = await file.read()
        s3_url = upload_file_to_storage(effective_principal.app_id, file_id, file.filename, content, file.content_type or "application/octet-stream")
        return {"file_id": file_id, "s3_url": s3_url, "filename": file.filename}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Upload failed", extra={"event": "upload_failed", "document_filename": file.filename})
        raise HTTPException(500, str(e))


def client_index_object(req: ObjectIndexRequest, principal: Principal):
    return _index_object(req, principal)


def index_object(req: ObjectIndexRequest, principal: Principal):
    return _index_object(req, principal)


def _index_object(req: ObjectIndexRequest, principal: Principal):
    require_ready()
    try:
        return run_index_object(
            runtime.application,
            req,
            principal,
            principal_for_request=database_principal,
            require_app_database=require_app_database,
            store_context=store_context,
            create_file_id=create_file_id,
            index_presigned_object=index_presigned_object,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Object index failed", extra={"event": "object_index_failed", "s3_url": req.s3_url})
        raise HTTPException(500, str(e))


def client_create_index_job(req: ObjectIndexRequest, principal: Principal):
    return _create_index_job(req, principal)


def create_index_job(req: AdminIndexJobRequest, principal: Principal):
    return _create_index_job(req, principal)


def _create_index_job(req: ObjectIndexRequest, principal: Principal):
    require_ready()
    try:
        return run_create_index_job(
            runtime.application,
            req,
            principal,
            principal_for_request=database_principal,
            require_app_database=require_app_database,
            create_file_id=create_file_id,
            enqueue_index_job=enqueue_index_job,
        )
    except HTTPException:
        raise
    except IndexQueueRejected as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Object index job failed", extra={"event": "object_index_job_failed", "s3_url": req.s3_url})
        raise HTTPException(500, str(e))


def presign_object(req: PresignRequest, _=None):
    bucket, object_name = parse_storage_url(req.s3_url)
    client = minio_client()
    try:
        url = client.presigned_get_object(bucket, object_name, expires=timedelta(seconds=req.expires_in))
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    public_endpoint = os.getenv("S3_PUBLIC_ENDPOINT_URL")
    if public_endpoint:
        internal = os.getenv("S3_ENDPOINT_URL", "")
        if internal:
            url = url.replace(internal.rstrip("/"), public_endpoint.rstrip("/"), 1)
    return {"presigned_url": url}


def files(limit: int = 50, cursor: str | None = None, app_id: str | None = None, principal: Principal | None = None):
    require_ready()
    try:
        page = runtime.application.database.list_files(
            database_principal(principal, app_id).app_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "files": [file_record(record) for record in page.files],
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
        "total": page.total,
    }


def chunks(req: ChunksQueryRequest, principal: Principal):
    require_ready()
    try:
        store = scoped_store(database_principal(principal, req.app_id))
        page = store.list_chunks(file_ids=req.file_ids, limit=req.limit, cursor=req.cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "chunks": [chunk_record(document) for document in page["documents"]],
        "next_cursor": page["next_cursor"],
        "has_more": page["has_more"],
    }


def sparse_chunks(req: ChunksQueryRequest, principal: Principal):
    require_ready()
    try:
        effective_principal = database_principal(principal, req.app_id)
        sparse = runtime.application.sparse
        if sparse is None or not hasattr(sparse, "list_chunks"):
            return {"chunks": [], "next_cursor": None, "has_more": False}
        with store_context(effective_principal):
            page = sparse.list_chunks(file_ids=req.file_ids, limit=req.limit, cursor=req.cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "chunks": [chunk_record(document) for document in page["documents"]],
        "next_cursor": page["next_cursor"],
        "has_more": page["has_more"],
    }


def dense_vector(app_id: str, chunk_id: str, principal: Principal):
    return _chunk_vector(app_id, chunk_id, principal, vector_type="dense")


def sparse_vector(app_id: str, chunk_id: str, principal: Principal):
    sparse = runtime.application.sparse
    store = runtime.application.store
    if (
        sparse is None
        or not _supports(sparse, "supports_sparse_vector")
        or not _supports(store, "supports_sparse_vector", sparse)
    ):
        raise HTTPException(status_code=400, detail="sparse vector is not supported by current sparse backend")
    return _chunk_vector(app_id, chunk_id, principal, vector_type="sparse")


def _supports(component: Any, method_name: str, *args) -> bool:
    method = getattr(component, method_name, None)
    if not callable(method):
        return False
    return bool(method(*args))


def _chunk_vector(app_id: str, chunk_id: str, principal: Principal, *, vector_type: str):
    require_ready()
    effective_principal = database_principal(principal, app_id)
    store = runtime.application.store
    method_name = f"get_{vector_type}_vector"
    method = getattr(store, method_name, None)
    if not callable(method):
        raise HTTPException(status_code=400, detail=f"{vector_type} vector is not supported by current store")
    try:
        with store_context(effective_principal):
            vector = method(chunk_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if vector is None:
        raise HTTPException(status_code=404, detail="chunk not found")
    return {"chunk_id": chunk_id, "type": vector_type, "vector": vector}


def client_delete_file(file_id: str, principal: Principal):
    return delete_index_file(file_id, principal)


def delete_file(file_id: str, app_id: str | None, principal: Principal):
    effective_principal = database_principal(principal, app_id)
    result = delete_index_file(file_id, effective_principal)
    if principal.type == "app":
        return result
    try:
        delete_storage_file(effective_principal.app_id, file_id)
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


def delete_index_file(file_id: str, principal: Principal) -> dict[str, Any]:
    require_ready()
    store = scoped_store(principal)
    deleted_chunks = store.delete_file_chunks(file_id)
    sparse = getattr(runtime.application, "sparse", None)
    if sparse is not None and hasattr(sparse, "delete_file_chunks"):
        with store_context(principal):
            sparse.delete_file_chunks(file_id)
    runtime.application.database.soft_delete_file(principal.app_id, file_id)
    return {"deleted_chunks": deleted_chunks}


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


def minio_client() -> Minio:
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
    parsed = urlparse(endpoint_url)
    endpoint = parsed.netloc or parsed.path
    secure = parsed.scheme == "https"
    return Minio(
        endpoint,
        access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        secure=secure,
    )


def delete_storage_file(app_id: str, file_id: str) -> int:
    bucket = os.getenv("S3_BUCKET", "rag")
    client = minio_client()
    if not client.bucket_exists(bucket):
        return 0
    prefix = storage_file_prefix(app_id, file_id)
    deleted_count = 0
    for item in client.list_objects(bucket, prefix=prefix, recursive=True):
        client.remove_object(bucket, item.object_name)
        deleted_count += 1
    return deleted_count


def file_record(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename": record.filename,
        "s3_url": record.s3_url,
        "size": record.size,
        "created_at": record.created_at,
        "indexed_at": record.indexed_at,
        "chunk_count": record.chunk_count,
        "status": record.status,
        "error": record.error,
    }


def storage_prefix(app_id: str) -> str:
    validate_app_id(app_id)
    return f"uploads/{app_id}/"


def storage_file_prefix(app_id: str, file_id: str) -> str:
    return f"{storage_prefix(app_id)}{file_id}/"


def upload_file_to_storage(app_id: str, file_id: str, filename: str, content: bytes, content_type: str) -> str:
    bucket = os.getenv("S3_BUCKET", "rag")
    object_name = f"{storage_file_prefix(app_id, file_id)}{Path(filename).name}"
    client = minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(
        bucket,
        object_name,
        BytesIO(content),
        length=len(content),
        content_type=content_type,
    )
    return f"s3://{bucket}/{object_name}"
