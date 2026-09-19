import asyncio
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile

from shared.config import ChunkingConfig, StorageConfig
from services.rag.core.api.schemas import BatchIndexRequest, FileIndexRequest, PresignRequest
from services.rag.core.api.services import batch_files
from services.rag.core.api.services import files as service
from services.rag.core.auth import Principal
from services.rag.core.index import service as index_service
from services.rag.core.scope import app_collection, current_app_id
from shared.upstream import UpstreamServiceError


pytestmark = pytest.mark.unit


@pytest.fixture
def stateless(monkeypatch, tmp_path):
    class Vector:
        def __init__(self):
            self.collections = set()
            self.documents = {}
            self.ensured = []

        @contextmanager
        def app_scope(self, app_id):
            with app_collection(app_id):
                yield

        def app_collection_exists(self, app_id):
            return app_id in self.collections

        def ensure_app_collection(self, app_id):
            assert current_app_id() == app_id
            self.ensured.append(app_id)
            self.collections.add(app_id)

        def add_file_chunks(self, chunks, file_id):
            self.documents[current_app_id(), file_id] = chunks
            return len(chunks)

        def delete_file_chunks(self, file_id):
            return len(self.documents.pop((current_app_id(), file_id), []))

    parser = Mock()
    parser.parse_file.side_effect = lambda url, **kwargs: {"blocks": [{"type": "text", "text": "first" if url.endswith("first") else "updated"}]}
    minio = Mock(side_effect=AssertionError("external presigned indexing must not use Minio"))
    monkeypatch.setattr(service, "Minio", minio)
    state = SimpleNamespace(
        ready=True, db_client=None, vector_client=Vector(), parser_client=parser,
        config=SimpleNamespace(storage=StorageConfig(endpoint_url=None), chunking=ChunkingConfig()),
    )
    return state, minio


def _request(**kwargs):
    return FileIndexRequest(
        presigned_url=kwargs.pop("presigned_url", "https://external.example/first"),
        s3_url="s3://external/docs/a.txt", **kwargs,
    )


@pytest.mark.parametrize("file_id", [None, "provided-file"])
def test_stateless_index_update_and_delete_keep_app_scope(stateless, file_id):
    state, minio = stateless
    principal = Principal(type="app", app_id="tenant_a")
    result = service.client_index_file(state, _request(file_id=file_id), principal)
    actual_id = result["file_id"]
    assert actual_id
    if file_id is not None:
        assert actual_id == file_id
    first = state.vector_client.documents["tenant_a", actual_id][0]
    assert first["id"] == index_service.stable_chunk_id("tenant_a", actual_id, 0)
    assert first["content"] == "first"
    assert first["metadata"]["filename"] == "a.txt"
    assert first["metadata"]["s3_url"] == "s3://external/docs/a.txt"
    assert first["metadata"]["chunk_index"] == 0
    assert first["metadata"]["created_at"]

    updated = service.index_file(
        state, _request(file_id=actual_id, presigned_url="https://external.example/updated"), principal,
    )
    assert updated == result
    documents = state.vector_client.documents["tenant_a", actual_id]
    assert len(documents) == 1
    assert documents[0]["content"] == "updated"
    assert documents[0]["id"] == first["id"]
    assert state.vector_client.ensured == ["tenant_a", "tenant_a"]
    assert service.client_delete_file(state, actual_id, principal) == {"deleted_chunks": 1}
    assert state.vector_client.documents == {}
    minio.assert_not_called()


def test_stateless_index_rejects_other_app_before_creating_collection(stateless):
    state, _ = stateless
    with pytest.raises(HTTPException) as error:
        service.index_file(state, _request(app_id="tenant_b"), Principal(type="app", app_id="tenant_a"))
    assert error.value.status_code == 403
    assert state.vector_client.ensured == []


@pytest.mark.parametrize("failure,status", [
    (RuntimeError("parser failed"), 500),
    (UpstreamServiceError(service="parser", error="parser timed out", retryable=True, status_code=504), 504),
])
@pytest.mark.parametrize("existing_file", [False, True])
def test_stateless_index_failure_preserves_error_without_metadata(stateless, failure, status, existing_file):
    state, minio = stateless
    principal = Principal(type="app", app_id="tenant_a")
    if existing_file:
        service.index_file(state, _request(file_id="file_a"), principal)
    original = dict(state.vector_client.documents)
    state.parser_client.parse_file.side_effect = failure
    with pytest.raises(HTTPException) as error:
        service.index_file(state, _request(file_id="file_a"), principal)
    assert error.value.status_code == status
    detail = error.value.detail
    assert set(detail) == {"success", "error", "service", "retryable", "file_id", "traceId"}
    assert detail["error"] == str(failure)
    assert detail["file_id"] == "file_a"
    assert len(detail["traceId"]) == 32
    assert detail["retryable"] is (failure.retryable if isinstance(failure, UpstreamServiceError) else False)
    assert state.vector_client.documents == original
    minio.assert_not_called()


def test_database_index_still_requires_explicit_collection_initialization(stateless):
    state, _ = stateless
    state.db_client = Mock()
    with pytest.raises(HTTPException) as error:
        service.index_file(state, _request(), Principal(type="app", app_id="tenant_a"))
    assert error.value.status_code == 409
    assert state.db_client.mock_calls == []
    assert state.vector_client.ensured == []


@pytest.mark.parametrize("mark_failed_error", [None, RuntimeError("failed status unavailable")])
def test_metadata_failure_after_vector_write_is_reported(stateless, mark_failed_error):
    state, _ = stateless
    state.vector_client.collections.add("tenant_a")
    state.db_client = Mock()
    state.db_client.upsert_file.side_effect = RuntimeError("metadata unavailable")
    state.db_client.mark_file_failed.side_effect = mark_failed_error
    with pytest.raises(HTTPException) as error:
        service.index_file(state, _request(file_id="file_a"), Principal(type="app", app_id="tenant_a"))
    assert error.value.status_code == 500
    assert error.value.detail["file_id"] == "file_a"
    assert error.value.detail["retryable"] is False
    assert state.vector_client.documents["tenant_a", "file_a"][0]["content"] == "first"
    state.db_client.mark_file_failed.assert_called_once()
    import json
    assert json.loads(state.db_client.mark_file_failed.call_args.args[2]) == {
        "error": "metadata unavailable", "service": "database", "retryable": False, "traceId": error.value.detail["traceId"],
    }

    state.db_client.upsert_file.side_effect = None
    result = service.index_file(state, _request(file_id="file_a"), Principal(type="app", app_id="tenant_a"))
    assert result == {"success": True, "error": None, "service": None, "retryable": False, "traceId": error.value.detail["traceId"], "file_id": "file_a"}
    assert len(state.vector_client.documents) == 1
    assert len(state.vector_client.documents["tenant_a", "file_a"]) == 1


def test_retryable_metadata_success_failure_is_retried_without_reparsing(stateless, monkeypatch):
    from shared.config import RetryConfig

    monkeypatch.setattr("shared.retry.time.sleep", lambda seconds: None)
    state, _ = stateless
    state.vector_client.collections.add("tenant_a")
    state.config.database = SimpleNamespace(retry=RetryConfig(max_attempts=3, interval_seconds=0.5))
    state.db_client = Mock()
    state.db_client.upsert_file.side_effect = [
        UpstreamServiceError(service="database", error="temporary", retryable=True, status_code=503),
        None,
    ]

    result = service.index_file(state, _request(file_id="file_a"), Principal(type="app", app_id="tenant_a"))

    assert result["success"] is True
    assert state.parser_client.parse_file.call_count == 1
    assert state.vector_client.documents["tenant_a", "file_a"][0]["content"] == "first"
    assert state.db_client.upsert_file.call_count == 2
    state.db_client.mark_file_failed.assert_not_called()


def test_batch_index_requires_file_id():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BatchIndexRequest(files=[{
            "presigned_url": "https://external.example/a",
            "s3_url": "s3://external/docs/a.txt",
        }])


@pytest.mark.anyio
async def test_batch_index_dispatches_single_file_requests(monkeypatch):
    import json
    import httpx

    calls = []
    original_client = httpx.AsyncClient

    async def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.path, request.headers["authorization"], request.headers["traceparent"], body))
        if body["file_id"] == "file_b":
            return httpx.Response(502, json={
                "success": False,
                "error": "parser unavailable",
                "service": "parser",
                "retryable": True,
                "traceId": "b" * 32,
                "file_id": "file_b",
            })
        return httpx.Response(200, json={
            "success": True,
            "error": None,
            "service": None,
            "retryable": False,
            "traceId": "a" * 32,
            "file_id": body["file_id"],
        })

    monkeypatch.setattr(
        batch_files.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    state = SimpleNamespace(config=SimpleNamespace(api=SimpleNamespace(
        batch_index=SimpleNamespace(
            base_url="http://rag:6000",
            max_files=10,
            max_concurrency=5,
        ),
        index_timeout=600,
    )))
    req = BatchIndexRequest(files=[
        {
            "file_id": "file_a",
            "presigned_url": "https://external.example/a",
            "s3_url": "s3://external/docs/a.txt",
            "filename": "a.txt",
        },
        {
            "file_id": "file_b",
            "presigned_url": "https://external.example/b",
            "s3_url": "s3://external/docs/b.txt",
            "filename": "b.txt",
        },
    ])

    result = await batch_files.index_file(state, req, Principal(type="app", app_id="tenant_a"), "Bearer app-key")

    assert result == {
        "success": False,
        "files": [
            {"success": True, "error": None, "service": None, "retryable": False, "traceId": "a" * 32, "file_id": "file_a"},
            {"success": False, "error": "parser unavailable", "service": "parser", "retryable": True, "traceId": "b" * 32, "file_id": "file_b"},
        ],
    }
    assert [call[0] for call in calls] == ["/api/v1/rag/files", "/api/v1/rag/files"]
    assert {call[1] for call in calls} == {"Bearer app-key"}
    assert {call[2] for call in calls} == {calls[0][2]}
    assert {call[3]["file_id"] for call in calls} == {"file_a", "file_b"}


@pytest.mark.anyio
async def test_batch_index_keeps_single_file_response_shape(monkeypatch):
    import json
    import httpx

    original_client = httpx.AsyncClient
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr(
        batch_files.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    state = SimpleNamespace(config=SimpleNamespace(api=SimpleNamespace(
        batch_index=SimpleNamespace(
            base_url="http://rag:6000",
            max_files=10,
            max_concurrency=5,
        ),
        index_timeout=600,
    )))
    req = BatchIndexRequest(files=[{
        "file_id": "file_a",
        "s3_url": "s3://external/docs/a.txt",
    }])

    result = await batch_files.index_file(state, req, Principal(type="app", app_id="tenant_a"), "Bearer app-key")

    assert result == {"success": True, "files": [{"success": True}]}
    assert calls == [{"file_id": "file_a", "s3_url": "s3://external/docs/a.txt"}]


@pytest.mark.parametrize("stage", ["download", "parse", "vector"])
def test_index_failure_stops_later_steps_without_retry(stateless, monkeypatch, stage):
    import httpx
    from shared.tracing import set_traceparent, reset_traceparent

    state, _ = stateless
    state.vector_client.collections.add("tenant_a")
    state.db_client = Mock()
    if stage == "download":
        operation = state.parser_client.parse_file
        operation.side_effect = UpstreamServiceError(service="parser", error="download failed", retryable=True, status_code=503)
    elif stage == "parse":
        operation = state.parser_client.parse_file
        operation.side_effect = RuntimeError("private document")
    else:
        operation = Mock(side_effect=RuntimeError("private connection credentials"))
        monkeypatch.setattr(state.vector_client, "add_file_chunks", operation)
    token = set_traceparent("00-" + "a" * 32 + "-" + "b" * 16 + "-01")
    try:
        with pytest.raises(HTTPException) as error:
            service.index_file(state, _request(file_id="file_a"), Principal(type="app", app_id="tenant_a"))
        assert error.value.detail["retryable"] is (stage == "download")
        assert error.value.detail["traceId"] == "a" * 32
    finally:
        reset_traceparent(token)
    assert operation.call_count == 1
    state.db_client.upsert_file.assert_not_called()
    assert state.vector_client.documents == {}


def test_stateless_file_listing_reports_unavailable(stateless):
    state, _ = stateless
    with pytest.raises(HTTPException) as error:
        service.files(state, principal=Principal(type="app", app_id="tenant_a"))
    assert error.value.status_code == 503


def test_storage_operations_report_unavailable_without_deleting_index(stateless):
    state, minio = stateless
    principal = Principal(type="app", app_id="tenant_a")
    service.index_file(state, _request(file_id="file_a"), principal)
    with pytest.raises(HTTPException) as error:
        service.presign_object(state, PresignRequest(s3_url="s3://external/docs/a.txt"))
    assert error.value.status_code == 503
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.upload_file(state, UploadFile(filename="a.txt", file=BytesIO(b"data")), "tenant_a", principal))
    assert error.value.status_code == 503
    with pytest.raises(HTTPException) as error:
        service.delete_file(state, "file_a", None, principal)
    assert error.value.status_code == 503
    assert ("tenant_a", "file_a") in state.vector_client.documents
    assert service.client_delete_file(state, "file_a", principal) == {"deleted_chunks": 1}
    minio.assert_not_called()
