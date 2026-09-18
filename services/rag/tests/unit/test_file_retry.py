import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.rag.clients.db.base import FileRecord
from services.rag.core.api.services import files
from services.rag.core.auth import Principal
from shared.upstream import UpstreamServiceError


pytestmark = pytest.mark.unit


class Database:
    def __init__(self):
        self.record = FileRecord(id="original", filename="report.pdf", s3_url="s3://rag/uploads/tenant/original/report.pdf", chunk_count=0, status="failed")
        self.error = None
        self.claimed = False

    def get_file(self, app_id, file_id):
        assert (app_id, file_id) == ("tenant", "original")
        return self.record

    def claim_file_retry(self, app_id, file_id):
        if self.claimed:
            return False
        self.claimed = True
        return True

    def get_presign_config(self, app_id):
        return "template"

    def mark_file_failed(self, app_id, file_id, error):
        self.error = json.loads(error)

    def create_file(self, app_id, file_id, filename, s3_url):
        return None

    def mark_file_indexing(self, app_id, file_id):
        return None

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0):
        return None


def test_retry_reuses_file_identity_and_delegates_presign(monkeypatch):
    calls = []
    state = SimpleNamespace(
        ready=True,
        db_client=Database(),
        vector_client=SimpleNamespace(app_collection_exists=lambda app_id: True, app_scope=lambda app_id: nullcontext()),
        config=SimpleNamespace(storage=SimpleNamespace(download_timeout=60)),
    )
    def presign(template, variables, **kwargs):
        assert variables == {"app_id": "tenant", "file_id": "original", "filename": "report.pdf", "s3_url": state.db_client.record.s3_url}
        return "https://example.com/fresh"
    monkeypatch.setattr(files, "fetch_presigned_url", presign)
    monkeypatch.setattr(files, "index_presigned_file", lambda state, file_id, presigned_url, s3_url, filename: calls.append((file_id, presigned_url, s3_url, filename)) or (1, 2))
    assert files.retry_file(state, "original", "tenant", Principal(type="admin", app_id="admin"))["success"]
    assert calls == [("original", "https://example.com/fresh", state.db_client.record.s3_url, "report.pdf")]


def test_index_file_fetches_presigned_url_when_missing(monkeypatch):
    state = SimpleNamespace(
        ready=True,
        db_client=Database(),
        vector_client=SimpleNamespace(app_scope=lambda app_id: nullcontext()),
        config=SimpleNamespace(storage=SimpleNamespace(download_timeout=60)),
    )
    def presign(template, variables, **kwargs):
        assert variables == {"app_id": "tenant", "file_id": "original", "filename": "report.pdf", "s3_url": state.db_client.record.s3_url}
        return "https://example.com/fresh"
    monkeypatch.setattr(files, "fetch_presigned_url", presign)
    monkeypatch.setattr(files, "require_app_database", lambda state, principal: None)
    monkeypatch.setattr(files, "index_presigned_file", lambda state, file_id, presigned_url, s3_url, filename: (1, 2))
    result = files.index_file(
        state,
        files.FileIndexRequest(file_id="original", s3_url=state.db_client.record.s3_url, filename="report.pdf"),
        Principal(type="app", app_id="tenant"),
    )
    assert result["success"] is True


def test_presign_failure_is_saved_and_returned_with_original_file_id(monkeypatch):
    state = SimpleNamespace(
        ready=True,
        db_client=Database(),
        vector_client=SimpleNamespace(app_collection_exists=lambda app_id: True, app_scope=lambda app_id: nullcontext()),
        config=SimpleNamespace(storage=SimpleNamespace(download_timeout=60)),
    )
    def fail(*args, **kwargs):
        raise UpstreamServiceError(service="presign", error="connection lost", retryable=True, status_code=503)
    monkeypatch.setattr(files, "fetch_presigned_url", fail)
    with pytest.raises(HTTPException) as error:
        files.retry_file(state, "original", "tenant", Principal(type="admin", app_id="admin"))
    assert error.value.detail["file_id"] == "original"
    assert error.value.detail["retryable"] is True
    assert state.db_client.error["error"] == "connection lost"
