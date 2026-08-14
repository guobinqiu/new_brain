import os
import logging
import threading
import tempfile
from io import BytesIO
from collections import deque
from datetime import timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
from pydantic import BaseModel, Field, model_validator
from bootstrap import Application
from indexing import create_file_id, index_file
from search import SearchPlan, _SearchExecutor
from config import SEARCH_CONFIG
from logging_config import configure_logging


logger = logging.getLogger("rag.app")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: Literal["dense", "sparse", "hybrid"] = SEARCH_CONFIG["default_mode"]
    sparse_mode: Literal["app", "vector"] = "app"
    top_k: int = Field(SEARCH_CONFIG["top_k"], ge=1, le=50)
    rerank: bool = SEARCH_CONFIG["rerank"]
    fetch_k: int = Field(SEARCH_CONFIG["fetch_k"], ge=1)
    dense_weight: float = Field(SEARCH_CONFIG["dense_weight"], ge=0, le=1)
    sparse_weight: float = Field(SEARCH_CONFIG["sparse_weight"], ge=0, le=1)
    rrf_k: int = Field(SEARCH_CONFIG["rrf_k"], ge=1)
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_fetch_k(self):
        if self.fetch_k < self.top_k:
            raise ValueError("fetch_k must be greater than or equal to top_k")
        if self.file_ids is not None and len(self.file_ids) == 0:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        return self


class ObjectIndexRequest(BaseModel):
    file_id: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    presigned_url: str = Field(..., min_length=1)
    s3_url: str = Field(..., min_length=1)
    filename: str | None = None

    @model_validator(mode="after")
    def validate_s3_url(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


class PresignRequest(BaseModel):
    s3_url: str = Field(..., min_length=1)
    expires_in: int = Field(3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_s3_url(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


application = Application()
STARTUP_IN_BACKGROUND = True
STARTUP_RETRY_MAX_INTERVAL_SECONDS = 30
SEARCH_TRACE_LIMIT = 50
_search_traces = deque(maxlen=SEARCH_TRACE_LIMIT)
_search_traces_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动进程后在后台初始化 RAG，避免数据库暂时不可用导致进程退出。"""
    configure_logging(application.config.logging)
    app.state.application = application
    stop_event = None
    if STARTUP_IN_BACKGROUND:
        stop_event = threading.Event()
        startup_thread = threading.Thread(target=_start_application_until_ready, args=(stop_event,), name="rag-startup", daemon=True)
        startup_thread.start()
    else:
        logger.info("Preloading models ...", extra={"event": "startup_preload"})
        application.start()
        logger.info("Startup model preload done", extra={"event": "startup_ready"})
    yield
    if stop_event is not None:
        stop_event.set()
    application.stop()
    logger.info("Application closed", extra={"event": "shutdown"})


app = FastAPI(title="Qdrant Knowledge Search API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/ready")
def ready():
    if not application.ready:
        raise HTTPException(503, "search is not initialized")
    return {"status": "ready"}

@app.get("/api/config")
def get_config():
    cfg = dict(SEARCH_CONFIG)
    cfg["config_name"] = application.config_name
    cfg["store"] = _store_config()
    cfg["dense"] = _component_config(application.config.dense)
    cfg["sparse"] = {
        "default_mode": "app",
        "available_modes": _available_sparse_modes(),
        "app": _component_config(application.config.sparse.app),
        "vector": _component_config(application.config.sparse.vector),
    }
    cfg["rerank"] = _component_config(application.config.rerank)
    cfg["ocr"] = _component_config(application.config.ocr)
    cfg["available_components"] = application.config.available_components
    return cfg

@app.get("/api/monitor")
def monitor():
    data = {
        "files": 0,
        "total_chunks": 0,
        "collections": {
            "chunks": application.config.store.collections.chunks,
        },
    }
    if application.ready:
        data.update(
            {
                "files": application.store.count_files(),
                "total_chunks": application.store.get_total_chunks(),
            }
        )
    return {
        "ready": application.ready,
        "profile": _profile(),
        "components": _components(),
        "capabilities": _capabilities(),
        "index_contract": _index_contract(),
        "data": data,
        "search_traces": _recent_search_traces(),
    }

def index_chunks(
    path: str,
    filename: str,
) -> dict:
    _require_ready()
    file_id = create_file_id()
    index_file(application, file_id, Path(path), filename)
    logger.info("Document indexed", extra={"event": "document_indexed", "document_filename": filename, "file_id": file_id})
    return {"file_id": file_id}


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
):
    if not file.filename:
        raise HTTPException(400, "No filename")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".txt", ".md", ".markdown", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise HTTPException(400, f"Unsupported file type: {ext}")
    
    try:
        content = await file.read()
        s3_url = _upload_file_to_storage(file.filename, content, file.content_type or "application/octet-stream")
        return {"s3_url": s3_url, "filename": file.filename}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Upload failed", extra={"event": "upload_failed", "document_filename": file.filename})
        raise HTTPException(500, str(e))


@app.post("/api/index")
def index_object(req: ObjectIndexRequest):
    _require_ready()
    filename = req.filename or _filename_from_s3_url(req.s3_url)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".pdf", ".txt", ".md", ".markdown", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise HTTPException(400, f"Unsupported file type: {ext}")
    file_id = req.file_id or create_file_id()
    path = Path(_download_presigned_file(req.presigned_url, ext))
    try:
        index_file(application, file_id, path, filename, extra_metadata={"s3_url": req.s3_url})
        return {"file_id": file_id}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Object index failed", extra={"event": "object_index_failed", "document_filename": filename, "s3_url": req.s3_url})
        raise HTTPException(500, str(e))


@app.post("/api/presign")
def presign_object(req: PresignRequest):
    bucket, object_name = _parse_s3_url(req.s3_url)
    client = _minio_client()
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


@app.post("/api/search")
def search(req: SearchRequest):
    _require_ready()
    if req.sparse_mode == "vector" and application.vector_sparse is None:
        raise HTTPException(400, "current profile does not support sparse_mode=vector")
    effective_rerank = bool(req.rerank and application.rerank is not None)
    plan = SearchPlan(
        req.query,
        mode=req.mode,
        top_k=req.top_k,
        rerank=effective_rerank,
        fetch_k=req.fetch_k,
        dense_weight=req.dense_weight,
        sparse_weight=req.sparse_weight,
        rrf_k=req.rrf_k,
        file_ids=req.file_ids,
        sparse_mode=req.sparse_mode,
    )
    executor = _SearchExecutor(
        plan,
        rerank=application.rerank,
        sparse=application.sparse,
        vector_sparse=application.vector_sparse,
        store=application.store,
        search_trace=application.config.logging.search_trace,
    )
    results = executor.execute()
    _append_search_trace(executor.trace.result)
    elapsed_ms = executor.trace.result["elapsed_ms"] if executor.trace.result else 0
    return {
        "results": results,
        "mode": req.mode,
        "rerank": effective_rerank,
        "fetch_k": req.fetch_k,
        "dense_weight": req.dense_weight,
        "sparse_weight": req.sparse_weight,
        "rrf_k": req.rrf_k,
        "sparse_mode": req.sparse_mode,
        "elapsed_ms": elapsed_ms,
    }


def _require_ready():
    if not application.ready:
        raise HTTPException(503, "search is not initialized")


def _available_sparse_modes() -> list[str]:
    modes = ["app"]
    if application.vector_sparse is not None:
        modes.append("vector")
    return modes


def _component_config(component: Any) -> dict[str, Any] | None:
    if component is None:
        return None
    data = {
        "name": getattr(component, "name", None),
        "model_name": getattr(component, "model_name", None),
        "model_path": getattr(component, "model_path", None),
        "tokenizer": getattr(component, "tokenizer", None),
        "import_path": getattr(component, "import_path", None),
    }
    return {key: value for key, value in data.items() if value is not None}


def _store_config() -> dict[str, Any]:
    store = application.config.store
    return {
        "type": store.type,
        "url": store.url,
        "uri": store.uri,
        "persist_dir": store.persist_dir,
        "timeout": store.timeout,
        "import_path": store.import_path,
        "collections": {
            "chunks": store.collections.chunks,
        },
    }


def _profile() -> dict[str, Any]:
    return {
        "config_name": application.config_name,
        "store": _store_config(),
        "dense": _component_config(application.config.dense),
        "sparse": {
            "app": _component_config(application.config.sparse.app),
            "vector": _component_config(application.config.sparse.vector),
        },
        "rerank": _component_config(application.config.rerank),
        "ocr": _component_config(application.config.ocr),
    }


def _capabilities() -> dict[str, Any]:
    return {
        "search_modes": ["dense", "sparse", "hybrid"],
        "sparse_modes": _available_sparse_modes(),
        "rerank": application.rerank is not None,
        "ocr": application.ocr is not None,
        "config_write": False,
        "restart": False,
    }


def _index_contract() -> dict[str, Any]:
    store = application.config.store
    return {
        "dense": _component_config(application.config.dense),
        "sparse_app": _component_config(application.config.sparse.app),
        "vector_sparse_enabled": application.config.sparse.vector is not None,
        "sparse_vector": _component_config(application.config.sparse.vector),
        "rerank": _component_config(application.config.rerank),
        "ocr": _component_config(application.config.ocr),
        "collections": {
            "chunks": store.collections.chunks,
        },
        "sparse_modes": _available_sparse_modes(),
    }


def _components() -> list[dict[str, Any]]:
    sparse_model = application.config.sparse.app
    sparse_error = application.component_errors.get("sparse") or application.component_errors.get("vector_sparse")
    sparse = {
        "name": "Sparse",
        "status": _component_status(application.sparse, enabled=application.config.sparse.app is not None, error=sparse_error),
        "model": _component_model(sparse_model),
        "mode": "app",
        "available_modes": _available_sparse_modes(),
    }
    return [
        {
            "name": "Store",
            "status": _component_status(application.store, enabled=application.config.store is not None, error=application.component_errors.get("store")),
            "model": application.config.store.type,
        },
        {
            "name": "Dense",
            "status": _component_status(application.dense, enabled=application.config.dense is not None, error=application.component_errors.get("dense")),
            "model": _component_model(application.config.dense),
        },
        sparse,
        {
            "name": "Rerank",
            "status": _component_status(application.rerank, enabled=application.config.rerank is not None, error=application.component_errors.get("rerank")),
            "model": _component_model(application.config.rerank),
        },
        {
            "name": "OCR",
            "status": _component_status(application.ocr, enabled=application.config.ocr is not None, error=application.component_errors.get("ocr")),
            "model": _component_model(application.config.ocr),
        },
    ]


def _component_status(component: Any, *, enabled: bool, error: str | None = None) -> str:
    if not enabled:
        return "disabled"
    if error:
        return "error"
    return "ready" if _is_ready(component) else "loading"


def _component_model(component_config: Any) -> str | None:
    if component_config is None:
        return None
    return getattr(component_config, "model_name", None) or getattr(component_config, "name", None)


def _is_ready(component: Any) -> bool:
    return bool(getattr(component, "ready", False))


def _start_application_until_ready(stop_event: threading.Event):
    retry_seconds = 1
    while not stop_event.is_set() and not application.ready:
        try:
            logger.info("Preloading models ...", extra={"event": "startup_preload"})
            application.start()
            logger.info("Startup model preload done", extra={"event": "startup_ready"})
            return
        except Exception as exc:
            logger.warning(
                "Application startup failed; retrying",
                exc_info=True,
                extra={"event": "startup_retry", "retry_seconds": retry_seconds, "error": str(exc)},
            )
            try:
                application.stop()
            except Exception:
                logger.exception("Application cleanup after failed startup failed", extra={"event": "startup_cleanup_failed"})
            stop_event.wait(retry_seconds)
            retry_seconds = min(retry_seconds * 2, STARTUP_RETRY_MAX_INTERVAL_SECONDS)

@app.get("/api/files")
def files(limit: int = 50, cursor: str | None = None):
    _require_ready()
    try:
        page = application.store.list_files(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "files": [_file_record(record) for record in page.files],
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@app.get("/api/chunks")
def chunks(limit: int = 50, cursor: str | None = None):
    _require_ready()
    try:
        page = _chunk_page(application.store.get_search_documents(None), limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return page


@app.delete("/api/files/{file_id}")
def delete_file(file_id: str):
    _require_ready()
    count = application.store.delete_file_chunks(file_id)
    logger.info(
        "File deleted",
        extra={
            "event": "file_deleted",
            "file_id": file_id,
            "deleted_chunks": count,
        },
    )
    return {"deleted_chunks": count}


def _file_record(record) -> dict[str, Any]:
    data = {
        "id": record.id,
        "filename": record.filename,
        "chunk_count": record.chunk_count,
    }
    return data


def _chunk_page(documents: list[dict], limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    start = int(cursor) if cursor else 0
    records = sorted(
        (_chunk_record(document) for document in documents),
        key=lambda item: (item["file_id"], item["chunk_index"], item["id"]),
    )
    page_records = records[start:start + limit]
    next_index = start + limit
    has_more = next_index < len(records)
    return {
        "chunks": page_records,
        "next_cursor": str(next_index) if has_more else None,
        "has_more": has_more,
    }


def _chunk_record(document: dict) -> dict[str, Any]:
    metadata = dict(document.get("metadata") or {})
    return {
        "id": document.get("id"),
        "file_id": metadata.get("file_id"),
        "filename": metadata.get("filename"),
        "chunk_index": metadata.get("chunk_index"),
        "s3_url": metadata.get("s3_url"),
        "content": document.get("content"),
    }


def _filename_from_s3_url(s3_url: str) -> str:
    _, object_name = _parse_s3_url(s3_url)
    filename = Path(object_name).name
    if not filename:
        raise HTTPException(400, "filename is required when s3_url has no object name")
    return filename


def _parse_s3_url(s3_url: str) -> tuple[str, str]:
    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    object_name = parsed.path.lstrip("/")
    if not bucket or not object_name:
        raise HTTPException(400, "s3_url must include bucket and object key")
    return bucket, object_name


def _minio_client() -> Minio:
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


def _upload_file_to_storage(filename: str, content: bytes, content_type: str) -> str:
    bucket = os.getenv("S3_BUCKET", "rag-dev")
    object_name = f"uploads/{create_file_id()}/{Path(filename).name}"
    client = _minio_client()
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


def _download_presigned_file(presigned_url: str, suffix: str) -> str:
    response = httpx.get(presigned_url, timeout=60)
    response.raise_for_status()
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(response.content)
        return handle.name
    finally:
        handle.close()


def _append_search_trace(trace: dict[str, Any] | None) -> None:
    if trace is None:
        return
    with _search_traces_lock:
        _search_traces.appendleft(trace)


def _recent_search_traces() -> list[dict[str, Any]]:
    with _search_traces_lock:
        return list(_search_traces)
