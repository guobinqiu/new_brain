from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from index.service import filename_from_s3_url, validate_supported_file_extension


logger = logging.getLogger("rag.indexing")


def index_object(application: Any, req: Any, principal: Any, *, principal_for_request, require_app_database, store_context, create_file_id, index_presigned_object) -> dict[str, str]:
    filename = req.filename or filename_from_s3_url(req.s3_url)
    _validate_index_request(application, filename, req.parser)
    parser = _internal_parser(req.parser)
    file_id = getattr(req, "file_id", None) or create_file_id()
    effective_principal = principal_for_request(principal, req.app_id)
    require_app_database(effective_principal)
    try:
        application.database.create_file(effective_principal.app_id, file_id, filename, req.s3_url)
        application.database.mark_file_indexing(effective_principal.app_id, file_id)
        with _store_context(store_context, effective_principal):
            index_kwargs = {
                "file_id": file_id,
                "presigned_url": req.presigned_url,
                "s3_url": req.s3_url,
                "filename": filename,
            }
            if parser is not None:
                index_kwargs["parser"] = parser
            count, file_size = index_presigned_object(application, **index_kwargs)
            application.database.upsert_file(
                effective_principal.app_id,
                file_id,
                filename,
                req.s3_url,
                size=file_size,
                chunk_count=count,
            )
        logger.info("Object indexed", extra={"event": "object_indexed", "document_filename": filename, "file_id": file_id, "s3_url": req.s3_url, "chunk_count": count})
        return {"file_id": file_id}
    except Exception as exc:
        _mark_failed(application, effective_principal.app_id, file_id, exc)
        raise


def create_index_job(application: Any, req: Any, principal: Any, *, principal_for_request, require_app_database, create_file_id, enqueue_index_job) -> dict[str, str]:
    filename = req.filename or filename_from_s3_url(req.s3_url)
    _validate_index_request(application, filename, req.parser)
    parser = _internal_parser(req.parser)
    file_id = getattr(req, "file_id", None) or create_file_id()
    effective_principal = principal_for_request(principal, req.app_id)
    require_app_database(effective_principal)
    try:
        application.database.create_file(effective_principal.app_id, file_id, filename, req.s3_url)
        enqueue_kwargs = {
            "app_id": effective_principal.app_id,
            "file_id": file_id,
            "presigned_url": req.presigned_url,
            "s3_url": req.s3_url,
            "filename": filename,
        }
        if parser is not None:
            enqueue_kwargs["parser"] = parser
        enqueue_index_job(**enqueue_kwargs)
        return {"file_id": file_id}
    except Exception as exc:
        _mark_failed(application, effective_principal.app_id, file_id, exc)
        raise


def _validate_index_request(application: Any, filename: str, parser: str | None) -> None:
    suffix = Path(filename).suffix.lower()
    validate_supported_file_extension(suffix)
    selected_parser = parser or application.config.parser.type
    if selected_parser == "standard" and suffix == ".pdf" and not application.parser.is_available("table"):
        raise ValueError(f"parser is unavailable: {selected_parser}")


def _internal_parser(parser: str | None) -> str | None:
    if parser is None:
        return None
    return {
        "standard": "table",
        "fast": "text",
    }[parser]


def _mark_failed(application: Any, app_id: str, file_id: str, exc: Exception) -> None:
    application.database.mark_file_failed(app_id, file_id, str(exc))


def _store_context(store_context, principal):
    if store_context is None:
        return nullcontext()
    return store_context(principal)
