import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from services.rag.core.api.services import files
from services.rag.core.auth import Principal


def test_upload_update_reuses_id_and_keeps_old_object(monkeypatch):
    calls = []
    record = SimpleNamespace(status="success")
    db = SimpleNamespace(get_file=lambda app_id, file_id: calls.append((app_id, file_id)) or record)
    state = SimpleNamespace(db_client=db, config=SimpleNamespace(storage=SimpleNamespace(bucket="rag")))
    monkeypatch.setattr(files, "_require_storage", lambda config: None)
    monkeypatch.setattr(files, "require_app_database", lambda state, principal: None)
    monkeypatch.setattr(files, "create_file_id", lambda: "version-2")
    stored = []
    client = SimpleNamespace(
        bucket_exists=lambda bucket: True,
        put_object=lambda bucket, key, data, **kwargs: stored.append((key, data.read())),
    )
    monkeypatch.setattr(files, "minio_client", lambda config: client)
    with BytesIO(b"new content") as content:
        result = asyncio.run(files.upload_file(
            state, UploadFile(filename="report.txt", file=content), "tenant",
            Principal(type="admin", app_id="admin"), file_id="original",
        ))
    assert calls == [("tenant", "original")]
    assert result == {
        "file_id": "original", "filename": "report.txt",
        "s3_url": "s3://rag/uploads/tenant/original/version-2/report.txt",
    }
    assert stored == [("uploads/tenant/original/version-2/report.txt", b"new content")]


@pytest.mark.parametrize("record,status", [(None, 404), (SimpleNamespace(status="indexing"), 409), (SimpleNamespace(status="queued"), 409)])
def test_upload_update_requires_existing_idle_file(monkeypatch, record, status):
    state = SimpleNamespace(db_client=SimpleNamespace(get_file=lambda *args: record), config=SimpleNamespace(storage=None))
    monkeypatch.setattr(files, "_require_storage", lambda config: None)
    monkeypatch.setattr(files, "require_app_database", lambda state, principal: None)
    with BytesIO(b"new content") as content, pytest.raises(HTTPException) as error:
        asyncio.run(files.upload_file(
            state, UploadFile(filename="report.txt", file=content), "tenant",
            Principal(type="admin", app_id="admin"), file_id="original",
        ))
    assert error.value.status_code == status
