import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from minio import Minio

from services.rag.core.api.index_errors import install_index_error_handlers
from services.rag.core.api.routes.apps import router as apps_router
from services.rag.core.api.routes.files import router as files_router
from services.rag.core.auth import Principal, issue_token
from services.rag.core.scope import app_collection
from services.rag.core.presign import fetch_presigned_url
from services.rag.tests.e2e.test_index_failure_http import http_server
from services.rag.tests.fixtures.database import isolated_pg
from shared.config import AdminAuthConfig, ApiConfig, AuthConfig, ChunkingConfig, StorageConfig
from shared.tracing import install_trace_middleware


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_presign_upstream_query_or_body(method):
    upstream = FastAPI()
    source = 's3://bucket/report "final" & details.pdf'

    @upstream.api_route("/sign", methods=["GET", "POST"])
    async def sign(request: Request):
        params = request.query_params if request.method == "GET" else await request.json()
        assert params["object"] == source
        return {"data": {"download_url": "https://example.com/fresh"}}

    with http_server(upstream) as url:
        config = {
            "url": url + "/sign", "method": method,
            "params" if method == "GET" else "body": {"object": "SOURCE_PLACEHOLDER"},
            "response_url_path": "data.download_url",
        }
        template = json.dumps(config).replace('"SOURCE_PLACEHOLDER"', '{{ s3_url | tojson }}')
        assert fetch_presigned_url(template, {"s3_url": source}, timeout=5) == "https://example.com/fresh"


def test_failed_index_refreshes_presign_and_reuses_file_id(isolated_pg):
    # PG、S3、HTTP 使用真实服务，解析及向量计算用确定性替身
    credential = isolated_pg.create_app("tenant")
    bucket = "presign-e2e-" + uuid.uuid4().hex
    storage = Minio("127.0.0.1:9000", access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"), secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"), secure=False)
    storage.make_bucket(bucket)

    class Parser:
        def parse_file(self, path, **kwargs):
            return [{"type": "text", "text": Path(path).read_text()}]

    class Vector:
        documents = {}

        def app_scope(self, app_id):
            return app_collection(app_id)

        def app_collection_exists(self, app_id):
            return True

        def add_file_chunks(self, chunks, file_id):
            self.documents[file_id] = chunks
            return len(chunks)

    app = FastAPI()
    app.include_router(files_router)
    app.include_router(apps_router)
    install_index_error_handlers(app)
    install_trace_middleware(app, service_name="rag")
    auth = AuthConfig(admin=AdminAuthConfig(username="test", password="test"), apps=[credential])
    app.state.config = SimpleNamespace(
        auth=auth, database=None, api=ApiConfig(), chunking=ChunkingConfig(),
        storage=StorageConfig(endpoint_url="http://127.0.0.1:9000", bucket=bucket, download_timeout=5),
    )
    app.state.ready = True
    app.state.db_client = isolated_pg
    app.state.vector_client = Vector()
    app.state.parser_client = Parser()
    headers = {"Authorization": "Bearer " + issue_token(auth, Principal(type="admin", app_id="admin"))}
    try:
        with http_server(app) as url, httpx.Client(base_url=url, headers=headers, timeout=15) as client:
            uploaded = client.post("/api/rag/upload", data={"app_id": "tenant"}, files={"file": ("report.txt", b"retry document", "text/plain")})
            assert uploaded.status_code == 200, uploaded.text
            record = uploaded.json()
            failed = client.post("/api/rag/files", json={**record, "app_id": "tenant", "presigned_url": url + "/missing"})
            assert failed.status_code >= 400
            assert isolated_pg.get_file("tenant", record["file_id"]).status == "failed"
            template = json.dumps({
                "url": url + "/api/v1/rag/presign", "method": "POST",
                "headers": {"Content-Type": "application/json", "Authorization": "Bearer " + credential.api_key},
                "body": {"s3_url": "SOURCE_PLACEHOLDER"}, "response_url_path": "presigned_url",
            }).replace('"SOURCE_PLACEHOLDER"', '{{ s3_url | tojson }}')
            saved = client.put("/api/rag/apps/tenant/presign-config", content=template, headers={"Content-Type": "text/plain"})
            assert saved.status_code == 200, saved.text
            assert client.get("/api/rag/apps/tenant/presign-config").json()["presign_config"] == template
            indexed = client.post("/api/rag/files", json={"app_id": "tenant", "file_id": record["file_id"]})
            assert indexed.status_code == 200, indexed.text
            assert indexed.json()["file_id"] == record["file_id"]
            assert indexed.json()["success"] is True
            assert set(indexed.json()) == {"success", "error", "retryable", "traceId", "file_id"}
            stored = isolated_pg.get_file("tenant", record["file_id"])
            assert stored.status == "success" and stored.error is None
            assert len(app.state.vector_client.documents) == 1
            assert isolated_pg.list_files("tenant").total == 1
            duplicate = client.post("/api/rag/files", json={"app_id": "tenant", "file_id": record["file_id"]})
            assert duplicate.status_code == 409
            assert isolated_pg.get_file("tenant", record["file_id"]).status == "success"
            updated = client.post("/api/rag/upload", data={"app_id": "tenant", "file_id": record["file_id"]}, files={"file": ("updated.txt", b"updated document", "text/plain")})
            assert updated.status_code == 200, updated.text
            replacement = updated.json()
            assert replacement["file_id"] == record["file_id"]
            assert replacement["s3_url"] != record["s3_url"]
            assert isolated_pg.get_file("tenant", record["file_id"]).s3_url == record["s3_url"]
            failed_update = client.post("/api/rag/files", json={**replacement, "app_id": "tenant", "presigned_url": url + "/missing"})
            assert failed_update.status_code >= 400
            assert isolated_pg.get_file("tenant", record["file_id"]).s3_url == replacement["s3_url"]
            assert app.state.vector_client.documents[record["file_id"]][0]["content"] == "retry document"
            reindexed = client.post("/api/rag/files", json={"app_id": "tenant", "file_id": record["file_id"]})
            assert reindexed.status_code == 200, reindexed.text
            assert reindexed.json()["success"] is True
            assert isolated_pg.get_file("tenant", record["file_id"]).filename == "updated.txt"
            assert isolated_pg.list_files("tenant").total == 1
            assert app.state.vector_client.documents[record["file_id"]][0]["content"] == "updated document"
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)
