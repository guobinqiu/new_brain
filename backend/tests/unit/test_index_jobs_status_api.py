import datetime
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from auth import Principal
from schema import AuthConfig, AdminAuthConfig


pytestmark = pytest.mark.unit


def _fake_config(tmp_path) -> AuthConfig:
    return AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )


def _fake_application(auth_config, store=None):
    import main

    config = replace(main.application.config, auth=auth_config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.store = store

        def start(self):
            pass

        def stop(self):
            pass

    return Application()


def _fake_job(job_id, status="finished", app_id="imsdom", file_id="file-1", chunk_count=3):
    class Status:
        value = status

    class Job:
        pass

    job = Job()
    job.id = job_id
    job.result = {"app_id": app_id, "file_id": file_id, "chunk_count": chunk_count}
    job.meta = {"app_id": app_id, "file_id": file_id, "filename": "test_ai.txt", "s3_url": "s3://bucket/test_ai.txt"}
    job.created_at = datetime.datetime(2026, 8, 17, 9, 0, 0)
    job.enqueued_at = datetime.datetime(2026, 8, 17, 9, 0, 0)
    job.started_at = datetime.datetime(2026, 8, 17, 9, 0, 2)
    job.ended_at = datetime.datetime(2026, 8, 17, 9, 0, 18)
    job.exc_info = None
    job.get_status = lambda refresh=True: Status()
    return job


def test_create_index_job_responses_only_job_id(monkeypatch, tmp_path):
    import main

    class Store:
        def app_collection_exists(self, app_id):
            return True

    auth_config = _fake_config(tmp_path)
    monkeypatch.setattr(main, "application", _fake_application(auth_config, store=Store()))
    monkeypatch.setattr(main, "STARTUP_IN_BACKGROUND", False)
    monkeypatch.setattr(main, "create_file_id", lambda: "generatedfile001")
    monkeypatch.setattr(main, "create_job_id", lambda: "job-1")
    monkeypatch.setattr(main, "enqueue_index_job", lambda **kwargs: _fake_job(kwargs["job_id"]))

    req = main.ObjectIndexRequest(
        presigned_url="http://example.com/presigned",
        s3_url="s3://bucket/example.txt",
        app_id="imsdom",
    )

    admin_resp = main.create_index_job(req, Principal(type="admin", app_id=""))
    client_resp = main.client_create_index_job(req, Principal(type="app", app_id="imsdom"))

    assert admin_resp == {"job_id": "job-1"}
    assert client_resp == {"job_id": "job-1"}


def test_admin_index_jobs_status_requires_jwt(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr(main, "application", _fake_application(_fake_config(tmp_path)))
    monkeypatch.setattr(main, "STARTUP_IN_BACKGROUND", False)

    with TestClient(main.app) as client:
        response = client.post("/api/admin/index/jobs/status", json={"job_ids": ["job-1"]})

    assert response.status_code == 401


def test_admin_index_jobs_status_returns_records_and_not_found(monkeypatch, tmp_path):
    import main
    from auth import Principal

    monkeypatch.setattr(main, "application", _fake_application(_fake_config(tmp_path)))
    monkeypatch.setattr(main, "STARTUP_IN_BACKGROUND", False)
    monkeypatch.setattr(
        main,
        "get_index_job",
        lambda job_id: _fake_job(job_id) if job_id == "job-1" else None,
    )

    result = main.admin_index_jobs_status(
        main.IndexJobsStatusRequest(job_ids=["job-1", "missing-1"]),
        Principal(type="admin", app_id=""),
    )

    assert len(result["jobs"]) == 2
    assert result["jobs"][0]["job_id"] == "job-1"
    assert result["jobs"][0]["status"] == "finished"
    assert result["jobs"][0]["file_id"] == "file-1"
    assert result["jobs"][0]["app_id"] == "imsdom"
    assert result["jobs"][1] == {"job_id": "missing-1", "status": "not_found"}