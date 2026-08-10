import os
import tempfile
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from bootstrap import Application
from document_parser import parse_file
from search import SearchPlan, _SearchExecutor
from config import SEARCH_CONFIG
from logging_config import configure_logging


logger = logging.getLogger("rag.app")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    top_k: int = Field(SEARCH_CONFIG["top_k"], ge=1, le=50)
    rerank: bool = False
    fetch_k: int = Field(SEARCH_CONFIG["fetch_k"], ge=1)
    namespace: str = Field("default", min_length=1)
    scope_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fetch_k(self):
        if self.fetch_k < self.top_k:
            raise ValueError("fetch_k must be greater than or equal to top_k")
        return self


application = Application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预加载所有模型，避免请求时等待模型加载。"""
    configure_logging(application.config.logging)
    logger.info("Preloading models ...", extra={"event": "startup_preload"})
    application.start()
    app.state.application = application
    logger.info("Startup model preload done", extra={"event": "startup_ready"})
    yield
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

@app.get("/api/config")
def get_config():
    return dict(SEARCH_CONFIG)

@app.put("/api/config")
def update_config(config: dict):
    for key in ("top_k", "fetch_k", "dense_weight", "sparse_weight", "rrf_k"):
        if key in config:
            SEARCH_CONFIG[key] = config[key]
    return dict(SEARCH_CONFIG)


def index_chunks(
    path: str,
    filename: str,
    collection_type: Literal["common", "scoped"] = "common",
    namespace: str = "default",
    scope_id: str | None = None,
) -> dict:
    if collection_type == "scoped" and not scope_id:
        raise ValueError("scope_id is required for scoped documents")
    _require_ready()
    chunks = parse_file(path, original_filename=filename, ocr=application.ocr)
    if collection_type == "common":
        count = application.store.add_common_documents(chunks, namespace=namespace)
    else:
        count = application.store.add_scoped_documents(chunks, namespace=namespace, scope_id=scope_id)
    logger.info(
        "Document indexed",
        extra={
            "event": "document_indexed",
            "document_filename": filename,
            "chunks": count,
            "collection_type": collection_type,
            "namespace": namespace,
            "scope_id": scope_id,
        },
    )
    return {
        "filename": filename,
        "chunks": count,
        "collection_type": collection_type,
        "namespace": namespace,
        "scope_id": scope_id,
        "status": "ok",
    }


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    collection_type: Literal["common", "scoped"] = Form("common"),
    namespace: str = Form("default"),
    scope_id: str | None = Form(None),
):
    if not file.filename:
        raise HTTPException(400, "No filename")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".txt", ".md", ".markdown", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise HTTPException(400, f"Unsupported file type: {ext}")
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()
        return index_chunks(
            tmp.name,
            filename=file.filename,
            collection_type=collection_type,
            namespace=namespace,
            scope_id=scope_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Upload failed", extra={"event": "upload_failed", "document_filename": file.filename})
        raise HTTPException(500, str(e))
    finally:
        os.unlink(tmp.name)

@app.post("/api/search")
def search(req: SearchRequest):
    _require_ready()
    import time
    start = time.perf_counter()
    plan = SearchPlan(
        req.query,
        mode=req.mode,
        top_k=req.top_k,
        rerank=req.rerank,
        fetch_k=req.fetch_k,
        namespace=req.namespace,
        scope_ids=req.scope_ids,
    )
    results = _SearchExecutor(
        plan,
        rerank=application.rerank,
        sparse=application.sparse,
        store=application.store,
        search_trace=application.config.logging.search_trace,
    ).execute()
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    return {"results": results, "mode": req.mode, "rerank": req.rerank, "fetch_k": req.fetch_k, "elapsed_ms": elapsed_ms}


def _require_ready():
    if not application.ready:
        raise HTTPException(503, "search is not initialized")

@app.get("/api/documents")
def documents(
    collection_type: Literal["all", "common", "scoped"] = "all",
    namespace: str = "default",
    scope_ids: list[str] = Query(default_factory=list),
):
    return {"documents": application.store.list_documents(collection_type=collection_type, namespace=namespace, scope_ids=scope_ids)}

@app.delete("/api/documents/{filename:path}")
def delete(
    filename: str,
    collection_type: Literal["common", "scoped"],
    namespace: str = "default",
    scope_id: str | None = None,
):
    if collection_type == "common":
        count = application.store.delete_common_document(filename, namespace=namespace)
    else:
        count = application.store.delete_scoped_document(filename, namespace=namespace, scope_id=scope_id)
    logger.info(
        "Document deleted",
        extra={
            "event": "document_deleted",
            "document_filename": filename,
            "deleted_chunks": count,
            "collection_type": collection_type,
            "namespace": namespace,
            "scope_id": scope_id,
        },
    )
    return {"deleted_chunks": count}
