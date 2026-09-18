import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psycopg
import pytest
import yaml
from minio import Minio
from psycopg import sql
from psycopg.conninfo import make_conninfo


ROOT = Path(__file__).resolve().parents[4]


@dataclass
class RunningServer:
    base_url: str
    admin_credentials: dict = field(repr=False)
    bucket: str
    node_id: str
    vector_backend: str


@contextmanager
def isolated_rag_server(tmp_path, *, vector_backend=None, rerank=False, inference_url=None):
    raw = yaml.safe_load((ROOT / "services/rag/config/rag.yaml").read_text())
    if vector_backend is None:
        enabled = [name for name in ("qdrant", "milvus") if raw["vector_db"][name]["enable"]]
        if len(enabled) != 1:
            raise ValueError("Basic E2E requires exactly one enabled local vector backend in rag.yaml")
        vector_backend = enabled[0]
    for name in ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud"):
        raw["vector_db"][name]["enable"] = name == vector_backend
    raw["search"]["mode"] = "dense"
    raw["search"]["rerank"] = rerank
    raw["chunking"]["text"] = {"chunk_size": 256, "chunk_overlap": 0}
    raw["logging"]["level"] = "WARNING"
    raw["api"]["rate_limit"] = "10000/minute"
    raw["api"]["rate_limit_index"] = "10000/minute"
    admin_credentials = {"username": "e2e_test", "password": uuid.uuid4().hex}
    raw["auth"]["admin"] = {"username": admin_credentials["username"]}
    schema = "rag_e2e_" + uuid.uuid4().hex
    bucket = schema.replace("_", "-")
    raw["storage"]["bucket"] = bucket
    database_url = os.environ.get("DATABASE_URL", raw["db"]["postgres"]["url"])
    env = dict(os.environ)
    if inference_url is not None:
        raw["inference"]["base_url"] = inference_url
        env["INFERENCE_API_KEY"] = "inference-e2e-key"
    config_path = tmp_path / "rag.yaml"
    config_path.touch(mode=0o600)
    config_path.write_text(yaml.safe_dump(raw))
    env["RAG_CONFIG_FILE"] = str(config_path)
    env["DATABASE_URL"] = make_conninfo(database_url, options=f"-c search_path={schema}")
    env["RAG_ADMIN_PASSWORD"] = admin_credentials["password"]
    env["RAG_PEERS"] = ""
    env["RAG_NODE_ID"] = schema
    endpoint = urlparse(raw["storage"]["endpoint_url"])
    storage = Minio(
        endpoint.netloc or endpoint.path,
        access_key=env.get("S3_ACCESS_KEY", "minioadmin"),
        secret_key=env.get("S3_SECRET_KEY", "minioadmin"),
        secure=endpoint.scheme == "https",
    )
    process = None
    bucket_created = False
    try:
        with psycopg.connect(database_url, autocommit=True) as database:
            database.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            try:
                assert not storage.bucket_exists(bucket), "E2E bucket must be new"
                storage.make_bucket(bucket)
                bucket_created = True
                log_path = tmp_path / "rag.log"
                log_path.touch(mode=0o600)
                with socket.socket() as listener, log_path.open("w") as log:
                    listener.bind(("127.0.0.1", 0))
                    listener.listen()
                    address = f"http://127.0.0.1:{listener.getsockname()[1]}"
                    process = subprocess.Popen(
                        [sys.executable, "-m", "uvicorn", "services.rag.app.main:app",
                         "--fd", str(listener.fileno()), "--no-access-log"],
                        cwd=ROOT, env=env, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
                    )
                    with httpx.Client(base_url=address, timeout=1, trust_env=False) as client:
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                pytest.fail("Isolated RAG process exited during startup")
                            try:
                                if client.get("/health").status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            time.sleep(0.2)
                        else:
                            pytest.fail("Isolated RAG startup timed out")
                    yield RunningServer(address, admin_credentials, bucket, schema, vector_backend)
            finally:
                try:
                    if process is not None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                finally:
                    try:
                        database.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                    finally:
                        if bucket_created:
                            for item in storage.list_objects(bucket, recursive=True):
                                storage.remove_object(bucket, item.object_name)
                            storage.remove_bucket(bucket)
    finally:
        config_path.unlink(missing_ok=True)


@contextmanager
def authenticated_client(server):
    with httpx.Client(base_url=server.base_url, timeout=180, trust_env=False) as client:
        login = client.post("/api/rag/login", json=server.admin_credentials)
        assert login.status_code == 200
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client


class AppApiClient:
    def __init__(self, client, app_id: str, api_key: str):
        self._client = client
        self.app_id = app_id
        self.api_key = api_key

    def post(self, path: str, *, json=None, **kwargs):
        return self._request("POST", path, json=json, **kwargs)

    def delete(self, path: str, *, json=None, **kwargs):
        return self._request("DELETE", path, json=json, **kwargs)

    def _request(self, method: str, path: str, *, json=None, **kwargs):
        body = b"" if json is None else json_dumps(json).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        return self._client.request(method, path, content=body, headers=headers, **kwargs)


def json_dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def upload_file(api_client, app_id: str, path: str | Path, *, filename: str | None = None, content_type: str = "text/plain") -> dict:
    file_path = Path(path)
    upload_name = filename or file_path.name
    with file_path.open("rb") as handle:
        response = api_client.post(
            "/api/rag/upload",
            data={"app_id": app_id},
            files={"file": (upload_name, handle, content_type)},
        )
    assert response.status_code == 200, response.text
    return response.json()


def presign_file(api_client, s3_url: str) -> str:
    response = api_client.post("/api/rag/presign", json={"s3_url": s3_url})
    assert response.status_code == 200, response.text
    return response.json()["presigned_url"]


def index_uploaded_file(
    app_api_client,
    api_client,
    path: str | Path,
    *,
    filename: str | None = None,
    content_type: str = "text/plain",
    file_id: str | None = None,
) -> str:
    uploaded = upload_file(api_client, app_api_client.app_id, path, filename=filename, content_type=content_type)
    presigned_url = presign_file(api_client, uploaded["s3_url"])
    indexed_file_id = file_id or uploaded["file_id"]
    response = app_api_client.post(
        "/api/v1/rag/files",
        json={
            "file_id": indexed_file_id,
            "presigned_url": presigned_url,
            "s3_url": uploaded["s3_url"],
            "filename": uploaded["filename"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "error": None, "retryable": False, "traceId": response.json()["traceId"], "file_id": indexed_file_id}
    assert len(response.json()["traceId"]) == 32
    return indexed_file_id


def indexed_file_record(app_api_client, file_id: str) -> dict:
    response = app_api_client._client.get("/api/rag/files", params={"app_id": app_api_client.app_id, "limit": 200})
    assert response.status_code == 200, response.text
    record = next((item for item in response.json()["files"] if item["id"] == file_id), None)
    assert record is not None
    return record
