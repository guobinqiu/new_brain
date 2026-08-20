import os
import asyncio
import logging
import threading
import json
import uuid
from io import BytesIO
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import asynccontextmanager, nullcontext
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from minio import Minio
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app_registry import AppRegistry
from auth import Principal, authenticate_client_signature, authenticate_password, issue_token, principal_from_authorization
from bootstrap import Application
from indexing import create_file_id, enqueue_index_job, index_file, index_presigned_object
from indexing.consumer import InlineIndexConsumer
from indexing.queue import IndexQueueRejected
from indexing.service import SUPPORTED_FILE_EXTENSIONS, filename_from_s3_url, parse_s3_url, validate_supported_file_extension
from log_buffer import logs_after, recent_logs
from search import SearchPlan, _SearchExecutor
from collection_names import validate_app_id
from config import SEARCH_CONFIG
from logging_config import configure_logging


logger = logging.getLogger("rag.app")


def normalize_file_id(file_id: str) -> str:
    try:
        return uuid.UUID(file_id).hex
    except ValueError as exc:
        raise ValueError("file_id must be a UUID") from exc


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    app_id: str | None = None
    mode: Literal["dense", "sparse", "hybrid"] = SEARCH_CONFIG["default_mode"]
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
    model_config = ConfigDict(extra="forbid")

    presigned_url: str = Field(..., min_length=1)
    s3_url: str = Field(..., min_length=1)
    filename: str | None = None
    app_id: str | None = None
    file_id: str | None = Field(None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_request(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        if self.file_id is not None:
            self.file_id = normalize_file_id(self.file_id)
        return self


class AdminIndexJobRequest(ObjectIndexRequest):
    file_id: str = Field(..., min_length=1, max_length=64)


class PresignRequest(BaseModel):
    s3_url: str = Field(..., min_length=1)
    expires_in: int = Field(3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_s3_url(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AppCreateRequest(BaseModel):
    app_id: str = Field(..., min_length=2, max_length=64)


class ChunksQueryRequest(BaseModel):
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None
    app_id: str | None = None
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_file_ids(self):
        if self.file_ids is not None and len(self.file_ids) == 0:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        return self


application = Application()
STARTUP_IN_BACKGROUND = True
STARTUP_RETRY_MAX_INTERVAL_SECONDS = 30
SEARCH_TRACE_LIMIT = 200
_search_traces = deque(maxlen=SEARCH_TRACE_LIMIT)
_search_traces_lock = threading.Lock()
_index_consumer: InlineIndexConsumer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动进程后在后台初始化 RAG，避免数据库暂时不可用导致进程退出。"""
    global _index_consumer
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
    # 进程内索引消费器随本进程常驻；空转时阻塞在 queue.get() 上，入队端点有
    # _require_ready 守卫，因此模型加载完成前启动是安全的。
    _index_consumer = InlineIndexConsumer(application)
    await _index_consumer.start()
    yield
    if _index_consumer is not None:
        await _index_consumer.stop()
        _index_consumer = None
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


def require_jwt(authorization: str | None = Header(None)) -> Principal:
    return principal_from_authorization(application.config.auth, authorization)


async def require_aksk(request: Request) -> Principal:
    return authenticate_client_signature(application.config.auth, request, await request.body())


@app.post("/api/login")
def login(req: LoginRequest):
    principal = authenticate_password(application.config.auth, req.username, req.password)
    return {
        "access_token": issue_token(application.config.auth, principal),
        "token_type": "Bearer",
    }


@app.get("/api/apps")
def list_apps(_: Principal = Depends(require_jwt)):
    registry = AppRegistry(application.config.auth.registry_file)
    return {
        "apps": [
            {
                "app_id": app_credential.app_id,
                "access_key": app_credential.access_key,
                "secret_key": app_credential.secret_key,
            }
            for app_credential in registry.list_apps()
        ]
    }


@app.post("/api/apps", status_code=201)
def create_app(req: AppCreateRequest, _: Principal = Depends(require_jwt)):
    registry = AppRegistry(application.config.auth.registry_file)
    try:
        if registry.get_app(req.app_id) is not None:
            raise ValueError("app_id already exists")
        credential = registry.create_app(req.app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "app_id": credential.app_id,
        "access_key": credential.access_key,
        "secret_key": credential.secret_key,
    }


@app.delete("/api/apps/{app_id}")
def delete_app(app_id: str, _: Principal = Depends(require_jwt)):
    registry = AppRegistry(application.config.auth.registry_file)
    try:
        deleted = registry.delete_app(app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "app not found")
    application.database.purge_app(app_id)
    return {"deleted": True}


@app.post("/api/apps/{app_id}/database")
def initialize_app_database(app_id: str, _: Principal = Depends(require_jwt)):
    _require_ready()
    try:
        application.store.ensure_app_collection(app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"app_id": app_id, "initialized": True}


@app.get("/api/apps/{app_id}/database")
def app_database_status(app_id: str, _: Principal = Depends(require_jwt)):
    _require_ready()
    return _app_database_status(app_id)


@app.delete("/api/apps/{app_id}/database")
def delete_app_database(app_id: str, _: Principal = Depends(require_jwt)):
    _require_ready()
    status = _app_database_status(app_id)
    if not status["exists"]:
        raise HTTPException(404, "app database not found")
    if status["chunk_count"] > 0:
        raise HTTPException(409, "app database is not empty")
    deleted = application.store.drop_app_collection(app_id)
    application.database.purge_app(app_id)
    return {"app_id": app_id, "deleted": deleted}


@app.get("/api/config")
def get_config(_: Principal = Depends(require_jwt)):
    cfg = dict(SEARCH_CONFIG)
    cfg["config_name"] = application.config_name
    cfg["store"] = _store_config()
    cfg["dense"] = _component_config(application.config.dense)
    cfg["sparse"] = _component_config(application.config.sparse)
    cfg["rerank"] = _component_config(application.config.rerank)
    cfg["ocr"] = _component_config(application.config.ocr)
    cfg["available_components"] = application.config.available_components
    return cfg

@app.get("/api/monitor")
def monitor(_: Principal = Depends(require_jwt)):
    return {
        "ready": application.ready,
        "profile": _profile(),
        "components": _components(),
        "capabilities": _capabilities(),
        "index_contract": _index_contract(),
    }


@app.get("/api/traces")
def traces(limit: int = 50, app_id: str | None = None, principal: Principal = Depends(require_jwt)):
    try:
        return _recent_search_traces(limit=limit, app_id=_app_filter(principal, app_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/logs/stream")
async def logs_stream(request: Request, _: Principal = Depends(require_jwt)):
    async def stream():
        initial_events, last_seq = _initial_log_events()
        for event in initial_events:
            yield event
        while not await request.is_disconnected():
            await asyncio.sleep(1)
            rows = logs_after(last_seq)
            for row in rows:
                last_seq = max(last_seq, row["seq"])
                yield _sse(row)

    return StreamingResponse(stream(), media_type="text/event-stream")


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
    app_id: str = Form(...),
    principal: Principal = Depends(require_jwt),
):
    effective_principal = _database_principal(principal, app_id)
    _require_app_database(effective_principal)
    if not file.filename:
        raise HTTPException(400, "No filename")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_FILE_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")
    
    try:
        file_id = create_file_id()
        content = await file.read()
        s3_url = _upload_file_to_storage(effective_principal.app_id, file_id, file.filename, content, file.content_type or "application/octet-stream")
        return {"file_id": file_id, "s3_url": s3_url, "filename": file.filename}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Upload failed", extra={"event": "upload_failed", "document_filename": file.filename})
        raise HTTPException(500, str(e))


@app.post("/api/open/index")
def client_index_object(req: ObjectIndexRequest, principal: Principal = Depends(require_aksk)):
    return _index_object(req, principal)


@app.post("/api/index")
def index_object(req: ObjectIndexRequest, principal: Principal = Depends(require_jwt)):
    return _index_object(req, principal)


def _index_object(req: ObjectIndexRequest, principal: Principal):
    _require_ready()
    filename = req.filename or _filename_from_s3_url(req.s3_url)
    ext = os.path.splitext(filename)[1].lower()
    try:
        validate_supported_file_extension(ext)
    except ValueError as e:
        raise HTTPException(400, str(e))
    file_id = getattr(req, "file_id", None) or create_file_id()
    try:
        effective_principal = _database_principal(principal, req.app_id)
        _require_app_database(effective_principal)
        with _store_context(effective_principal):
            count, file_size = index_presigned_object(
                application,
                file_id=file_id,
                presigned_url=req.presigned_url,
                s3_url=req.s3_url,
                filename=filename,
            )
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
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Object index failed", extra={"event": "object_index_failed", "document_filename": filename, "s3_url": req.s3_url})
        raise HTTPException(500, str(e))


@app.post("/api/open/index/jobs", status_code=202)
def client_create_index_job(req: ObjectIndexRequest, principal: Principal = Depends(require_aksk)):
    return _create_index_job(req, principal)


@app.post("/api/index/jobs", status_code=202)
def create_index_job(req: AdminIndexJobRequest, principal: Principal = Depends(require_jwt)):
    return _create_index_job(req, principal)


def _create_index_job(req: ObjectIndexRequest, principal: Principal):
    _require_ready()
    filename = req.filename or _filename_from_s3_url(req.s3_url)
    ext = os.path.splitext(filename)[1].lower()
    try:
        validate_supported_file_extension(ext)
    except ValueError as e:
        raise HTTPException(400, str(e))
    file_id = getattr(req, "file_id", None) or create_file_id()
    effective_principal = _database_principal(principal, req.app_id)
    try:
        _require_app_database(effective_principal)
        enqueue_index_job(
            app_id=effective_principal.app_id,
            file_id=file_id,
            presigned_url=req.presigned_url,
            s3_url=req.s3_url,
            filename=filename,
        )
        return {"file_id": file_id}
    except HTTPException:
        raise
    except IndexQueueRejected as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Object index job failed", extra={"event": "object_index_job_failed", "document_filename": filename, "s3_url": req.s3_url})
        raise HTTPException(500, str(e))


@app.post("/api/presign")
def presign_object(req: PresignRequest, _: Principal = Depends(require_jwt)):
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


@app.post("/api/open/search")
def client_search(req: SearchRequest, principal: Principal = Depends(require_aksk)):
    return _search(req, principal)


@app.post("/api/search")
def search(req: SearchRequest, principal: Principal = Depends(require_jwt)):
    return _search(req, principal)


def _search(req: SearchRequest, principal: Principal):
    _require_ready()
    search_principal = _database_principal(principal, req.app_id)
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
    )
    executor = _SearchExecutor(
        plan,
        rerank=application.rerank,
        sparse=application.sparse,
        store=_scoped_store(search_principal),
        search_trace=application.config.logging.search_trace,
    )
    results = executor.execute()
    _append_search_trace(executor.trace.result, app_id=search_principal.app_id)
    elapsed_ms = executor.trace.result["elapsed_ms"] if executor.trace.result else 0
    return {
        "results": results,
        "mode": req.mode,
        "rerank": effective_rerank,
        "fetch_k": req.fetch_k,
        "dense_weight": req.dense_weight,
        "sparse_weight": req.sparse_weight,
        "rrf_k": req.rrf_k,
        "elapsed_ms": elapsed_ms,
    }


def _require_ready():
    if not application.ready:
        raise HTTPException(503, "search is not initialized")


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
    }


def _profile() -> dict[str, Any]:
    return {
        "config_name": application.config_name,
        "store": _store_config(),
        "dense": _component_config(application.config.dense),
        "sparse": _component_config(application.config.sparse),
        "rerank": _component_config(application.config.rerank),
        "ocr": _component_config(application.config.ocr),
    }


def _capabilities() -> dict[str, Any]:
    return {
        "search_modes": ["dense", "sparse", "hybrid"],
        "rerank": application.rerank is not None,
        "ocr": application.ocr is not None,
        "config_write": False,
        "restart": False,
    }


def _index_contract() -> dict[str, Any]:
    return {
        "dense": _component_config(application.config.dense),
        "sparse": _component_config(application.config.sparse),
        "rerank": _component_config(application.config.rerank),
        "ocr": _component_config(application.config.ocr),
    }


def _components() -> list[dict[str, Any]]:
    sparse_error = application.component_errors.get("sparse")
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
        {
            "name": "Sparse",
            "status": _component_status(application.sparse, enabled=application.config.sparse is not None, error=sparse_error),
            "model": _component_model(application.config.sparse),
        },
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
        {
            "name": "database",
            "status": _component_status(application.database, enabled=True, error=application.component_errors.get("database")),
        },
    ]


def _component_status(component: Any, *, enabled: bool, error: str | None = None) -> str:
    if not enabled:
        return "disabled"
    if error:
        return "error"
    if not application.ready:
        return "loading"
    return "ready" if _is_ready(component) else "loading"


def _component_model(component_config: Any) -> str | None:
    if component_config is None:
        return None
    return getattr(component_config, "model_name", None) or getattr(component_config, "name", None)


def _is_ready(component: Any) -> bool:
    return bool(getattr(component, "ready", False))


def _store_context(principal: Principal):
    principal = _effective_principal(principal)
    if not principal.app_id:
        return nullcontext()
    context = getattr(application.store, "app_context", None)
    if callable(context):
        return context(principal.app_id)
    return nullcontext()


def _effective_principal(principal) -> Principal:
    if isinstance(principal, Principal):
        return principal
    return Principal(type="admin", app_id="")


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
def files(limit: int = 50, cursor: str | None = None, direction: str = "next", app_id: str | None = None, principal: Principal = Depends(require_jwt)):
    _require_ready()
    try:
        page = application.database.list_files(
            _database_principal(principal, app_id).app_id,
            limit=limit,
            cursor=cursor,
            direction=direction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "files": [_file_record(record) for record in page.files],
        "prev_cursor": page.prev_cursor,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@app.post("/api/chunks")
def chunks(req: ChunksQueryRequest, principal: Principal = Depends(require_jwt)):
    _require_ready()
    try:
        scoped_store = _scoped_store(_database_principal(principal, req.app_id))
        page = scoped_store.list_chunks(file_ids=req.file_ids, limit=req.limit, cursor=req.cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "chunks": [_chunk_record(document) for document in page["documents"]],
        "next_cursor": page["next_cursor"],
        "has_more": page["has_more"],
    }


@app.delete("/api/open/files/{file_id}")
def client_delete_file(file_id: str, principal: Principal = Depends(require_aksk)):
    return _delete_index_file(file_id, principal)


@app.delete("/api/files/{file_id}")
def delete_file(file_id: str, app_id: str | None = None, principal: Principal = Depends(require_jwt)):
    effective_principal = _database_principal(principal, app_id)
    result = _delete_index_file(file_id, effective_principal)
    _delete_storage_file(effective_principal.app_id, file_id)
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


def _delete_index_file(file_id: str, principal: Principal) -> dict[str, Any]:
    _require_ready()
    scoped_store = _scoped_store(principal)
    deleted_chunks = scoped_store.delete_file_chunks(file_id)
    application.database.soft_delete_file(principal.app_id, file_id)
    return {"deleted_chunks": deleted_chunks}


def _chunk_record(document: dict) -> dict[str, Any]:
    metadata = dict(document.get("metadata") or {})
    return {
        "id": document.get("id"),
        "file_id": metadata.get("file_id"),
        "filename": metadata.get("filename"),
        "chunk_index": metadata.get("chunk_index"),
        "s3_url": metadata.get("s3_url"),
        "created_at": _iso_datetime(metadata.get("created_at")),
        "content": document.get("content"),
    }


def _database_principal(principal: Principal, app_id: str | None) -> Principal:
    principal = _effective_principal(principal)
    if principal.type == "admin":
        selected_app_id = app_id or principal.app_id
        if not selected_app_id:
            raise HTTPException(status_code=400, detail="app_id is required")
        validate_app_id(selected_app_id)
        return Principal(type="admin", app_id=selected_app_id)
    if app_id and app_id != principal.app_id:
        raise HTTPException(status_code=403, detail="app_id is not allowed")
    return principal


def _app_filter(principal: Principal, app_id: str | None) -> str | None:
    principal = _effective_principal(principal)
    if principal.type == "admin":
        if app_id:
            validate_app_id(app_id)
        return app_id
    if app_id and app_id != principal.app_id:
        raise HTTPException(status_code=403, detail="app_id is not allowed")
    return principal.app_id


def _scoped_store(principal: Principal):
    scoped_methods = {
        "delete_file_chunks",
        "get_search_documents",
        "get_total_chunks",
        "list_chunks",
        "search_dense",
        "search_hybrid",
        "search_sparse",
    }

    class ScopedStore:
        def __getattr__(self, name):
            attr = getattr(application.store, name)
            if not callable(attr) or name not in scoped_methods:
                return attr

            def call(*args, **kwargs):
                if not _app_database_exists(principal):
                    return 0 if name in {"delete_file_chunks", "get_total_chunks"} else []
                with _store_context(principal):
                    return attr(*args, **kwargs)

            return call

    return ScopedStore()


def _require_app_database(principal: Principal) -> None:
    principal = _effective_principal(principal)
    if principal.app_id and not _app_database_exists(principal):
        raise HTTPException(status_code=409, detail="app database is not initialized")


def _app_database_status(app_id: str) -> dict[str, Any]:
    try:
        validate_app_id(app_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    principal = Principal(type="admin", app_id=app_id)
    exists = _app_database_exists(principal)
    chunk_count = _scoped_store(principal).get_total_chunks(None) if exists else 0
    return {
        "app_id": app_id,
        "exists": exists,
        "chunk_count": chunk_count,
        "empty": chunk_count == 0,
    }


def _app_database_exists(principal: Principal) -> bool:
    principal = _effective_principal(principal)
    if not principal.app_id:
        return True
    return application.store.app_collection_exists(principal.app_id)


def _filename_from_s3_url(s3_url: str) -> str:
    try:
        return filename_from_s3_url(s3_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _parse_s3_url(s3_url: str) -> tuple[str, str]:
    try:
        return parse_s3_url(s3_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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


def _delete_storage_file(app_id: str, file_id: str) -> int:
    bucket = os.getenv("S3_BUCKET", "rag-dev")
    client = _minio_client()
    if not client.bucket_exists(bucket):
        return 0
    prefix = _storage_file_prefix(app_id, file_id)
    deleted_count = 0
    for item in client.list_objects(bucket, prefix=prefix, recursive=True):
        client.remove_object(bucket, item.object_name)
        deleted_count += 1
    return deleted_count


def _file_record(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename": record.filename,
        "s3_url": record.s3_url,
        "size": record.size,
        "created_at": record.created_at,
        "chunk_count": record.chunk_count,
    }


def _storage_prefix(app_id: str) -> str:
    validate_app_id(app_id)
    return f"uploads/{app_id}/"


def _storage_file_prefix(app_id: str, file_id: str) -> str:
    return f"{_storage_prefix(app_id)}{file_id}/"


def _upload_file_to_storage(app_id: str, file_id: str, filename: str, content: bytes, content_type: str) -> str:
    bucket = os.getenv("S3_BUCKET", "rag-dev")
    object_name = f"{_storage_file_prefix(app_id, file_id)}{Path(filename).name}"
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


def _append_search_trace(trace: dict[str, Any] | None, app_id: str) -> None:
    if trace is None:
        return
    trace = {**trace, "app_id": app_id}
    with _search_traces_lock:
        _search_traces.appendleft(trace)


def _recent_search_traces(limit: int = 50, app_id: str | None = None) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    with _search_traces_lock:
        rows = list(_search_traces)
    if app_id:
        rows = [row for row in rows if row.get("app_id") == app_id]
    return {"traces": rows[:limit]}


def _initial_log_events(limit: int = 200) -> tuple[list[str], int]:
    last_seq = 0
    events = []
    for row in recent_logs(limit):
        last_seq = max(last_seq, row["seq"])
        events.append(_sse(row))
    return events, last_seq


def _sse(row: dict[str, Any]) -> str:
    return f"data: {json.dumps(row, ensure_ascii=False, default=str)}\n\n"


def _iso_datetime(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().isoformat(timespec="seconds")
