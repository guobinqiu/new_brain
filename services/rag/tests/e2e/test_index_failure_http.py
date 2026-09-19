import json
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from services.inference.app.main import app as inference_app
from services.inference.providers.siliconflow import SiliconFlowInferenceClient
from services.rag.clients.inference import HttpInferenceClient
from services.rag.clients.parser import HttpParserClient
from services.rag.core.api.routes.files import router
from services.rag.core.api.index_errors import install_index_error_handlers
from services.rag.core.auth import AppCredential
from services.rag.core.scope import app_collection
from shared.config import AdminAuthConfig, ApiConfig, AuthConfig, ChunkingConfig, StorageConfig
from shared.tracing import install_trace_middleware


pytestmark = pytest.mark.e2e


@contextmanager
def http_server(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Test HTTP server failed to start")
                time.sleep(0.01)
            yield address
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


@pytest.mark.parametrize("failure", ["download", "parser", "payment", "rate_limit", "overload", "malformed", "metadata", "success"])
def test_index_failure_crosses_http_hops_once(monkeypatch, failure):
    # 真实 HTTP 链路，供应商和存储使用可控故障替身，不访问云账号
    calls = {"download": 0, "parser": 0, "embedding": 0, "metadata": 0}
    supplier = FastAPI()

    @supplier.get("/source")
    def source():
        calls["download"] += 1
        return PlainTextResponse("document", status_code=403 if failure == "download" else 200)

    @supplier.post("/v1/parse/file")
    def parse(request: Request, body: dict):
        assert request.headers["traceparent"].split("-")[1] == "a" * 32
        calls["parser"] += 1
        assert body["filename"] == "a.txt"
        downloaded = httpx.get(body["presigned_url"])
        if not downloaded.is_success:
            return JSONResponse({"error": downloaded.text, "retryable": False, "traceId": "a" * 32}, status_code=502)
        if failure == "parser":
            return JSONResponse({"private": "document"}, status_code=500)
        return {"blocks": [{"type": "text", "text": "document"}]}

    @supplier.post("/embeddings")
    def embed(request: Request):
        assert "traceparent" not in request.headers
        calls["embedding"] += 1
        if failure in ("payment", "rate_limit"):
            return JSONResponse({"message": "Provider rejected request; api_key=private-secret"}, status_code=402 if failure == "payment" else 429)
        if failure == "overload":
            return JSONResponse({"code": 50505, "message": "model overloaded"}, status_code=503)
        if failure == "malformed":
            return {"private": "invalid embeddings"}
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setenv("SERVICE_API_KEY", "test-service-key")
    with http_server(supplier) as supplier_url:
        remote = SiliconFlowInferenceClient(base_url=supplier_url, api_key="test", dense_model="test", rerank_model=None)
        monkeypatch.setattr(inference_app.state, "dense", remote.dense, raising=False)
        monkeypatch.setattr(inference_app.state, "sparse", None, raising=False)
        monkeypatch.setattr(inference_app.state, "rerank", None, raising=False)
        try:
            with http_server(inference_app) as inference_url:
                inference = HttpInferenceClient(inference_url, api_key="test-service-key")
                parser = HttpParserClient(supplier_url)
                try:
                    inference.start()

                    class Vector:
                        documents = {}

                        def app_scope(self, app_id):
                            return app_collection(app_id)

                        def app_collection_exists(self, app_id):
                            return True

                        def add_file_chunks(self, chunks, file_id):
                            inference.dense.embed_documents([chunk["content"] for chunk in chunks])
                            self.documents[file_id] = chunks
                            return len(chunks)

                    stored_errors = []

                    class Database:
                        def create_file(self, *args):
                            pass

                        def mark_file_indexing(self, *args):
                            pass

                        def mark_file_failed(self, *args):
                            stored_errors.append(json.loads(args[2]))

                        def upsert_file(self, *args, **kwargs):
                            calls["metadata"] += 1
                            if failure == "metadata":
                                raise RuntimeError("private database credentials")

                    rag = FastAPI()
                    rag.include_router(router)
                    install_index_error_handlers(rag)
                    install_trace_middleware(rag, service_name="rag")
                    rag.state.ready = True
                    rag.state.db_client = Database()
                    rag.state.vector_client = Vector()
                    rag.state.parser_client = parser
                    rag.state.config = SimpleNamespace(
                        database=None, api=ApiConfig(), chunking=ChunkingConfig(), storage=StorageConfig(download_timeout=10),
                        auth=AuthConfig(admin=AdminAuthConfig(username="test", password="test"), apps=[AppCredential(app_id="tenant_a", api_key="app-key")]),
                    )
                    with http_server(rag) as rag_url, httpx.Client(base_url=rag_url, timeout=10, trust_env=False) as client:
                        traceparent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
                        response = client.post("/api/v1/rag/files", headers={
                            "Authorization": "Bearer app-key", "traceparent": traceparent,
                        }, json={"file_id": "same-id", "filename": "a.txt", "s3_url": "s3://bucket/a.txt", "presigned_url": supplier_url + "/source"})
                    assert response.status_code == (200 if failure == "success" else 500 if failure == "metadata" else 502)
                    detail = response.json()
                    assert set(detail) == {"success", "error", "retryable", "file_id", "traceId"}
                    assert detail["file_id"] == "same-id"
                    assert detail["traceId"] == "a" * 32
                    assert detail["success"] is (failure == "success")
                    assert detail["retryable"] is (failure == "overload")
                    if failure in {"parser", "payment", "malformed"}:
                        assert "private" in response.text
                    if failure != "success":
                        assert set(stored_errors[0]) == {"error", "retryable", "traceId"}
                        assert stored_errors[0]["retryable"] == detail["retryable"]
                        assert stored_errors[0]["traceId"] == detail["traceId"]
                    if failure == "metadata":
                        assert stored_errors[0]["error"] == "private database credentials"
                    assert calls["download"] <= 1
                    assert calls["parser"] <= 1
                    assert calls["metadata"] <= 1
                    assert calls["embedding"] <= (3 if failure == "overload" else 1)
                    assert calls["metadata"] == (1 if failure in {"metadata", "success"} else 0)
                    assert bool(rag.state.vector_client.documents) == (failure in {"metadata", "success"})
                finally:
                    parser.close()
                    inference.close()
        finally:
            remote.close()

@pytest.mark.parametrize("status", [401, 422, 429])
def test_index_rejection_returns_index_protocol(status):
    app = FastAPI()
    install_index_error_handlers(app)
    install_trace_middleware(app, service_name="rag")

    @app.post("/api/rag/files")
    def index(count: int):
        raise HTTPException(status_code=status, detail="request rejected")

    @app.get("/other")
    def other():
        raise HTTPException(status_code=401, detail="request rejected")

    with http_server(app) as url, httpx.Client(base_url=url) as client:
        response = client.post("/api/rag/files", params={"count": "invalid" if status == 422 else "1"})
        assert response.status_code == status
        body = response.json()
        assert set(body) == {"success", "error", "retryable", "traceId", "file_id"}
        assert body["success"] is False
        assert body["retryable"] is False
        assert body["file_id"]
        assert len(body["traceId"]) == 32
        assert client.get("/other").json() == {"detail": "request rejected"}
