import pytest

from shared.upstream import UpstreamServiceError


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("message", ["original error", None])
def test_index_route_returns_flat_error(monkeypatch, message):
    import json
    from types import SimpleNamespace
    from fastapi import HTTPException
    from services.rag.core.api.routes import files
    from services.rag.core.index.errors import index_error_detail
    from shared.config import ApiConfig

    error = UpstreamServiceError(service="parser", error=message, retryable=False, status_code=502)
    detail = index_error_detail(error, "file-a")

    def fail(*args):
        raise HTTPException(502, detail)

    monkeypatch.setattr(files.service, "index_file", fail)
    state = SimpleNamespace(config=SimpleNamespace(api=ApiConfig(index_timeout=780)))
    response = files.open_index_file(SimpleNamespace(app=SimpleNamespace(state=state)), object(), object())
    assert response.status_code == 502
    assert json.loads(response.body) == {"success": False, "error": message, "retryable": False, "file_id": "file-a", "traceId": detail["traceId"]}


def test_request_timeout_uses_remaining_budget(monkeypatch):
    from shared import deadline

    now = [10.0]
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now[0])
    assert deadline.request_timeout(60) == 60
    with deadline.index_deadline(20):
        now[0] = 15
        assert deadline.request_timeout(60) == 15
        now[0] = 30
        with pytest.raises(UpstreamServiceError) as error:
            deadline.check_deadline()
        assert error.value.retryable is False
    assert deadline.request_timeout(60) == 60


@pytest.mark.parametrize("endpoint", ["admin_index_file", "open_index_file"])
def test_sync_index_deadline_stops_next_stage(monkeypatch, endpoint):
    from types import SimpleNamespace
    from services.rag.core.api.routes import files
    from services.rag.core.api.schemas import FileIndexRequest
    from shared.config import ApiConfig, AppConfig, AuthConfig, AdminAuthConfig, SearchConfig, StorageConfig, ServiceClientsConfig, VectorServiceConfig
    from shared import deadline

    now = [10.0]
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now[0])
    writes = []

    def blocked_index(*args):
        assert deadline.request_timeout(60) == 20
        now[0] = 31
        deadline.check_deadline()
        writes.append("write")

    monkeypatch.setenv("INDEX_TIMEOUT", "1")
    monkeypatch.setattr(files.service, "index_file", blocked_index)
    config = AppConfig(
        search=SearchConfig(),
        auth=AuthConfig(admin=AdminAuthConfig(username="admin", password="test")),
        services=ServiceClientsConfig(vector=VectorServiceConfig(provider="qdrant", base_url="http://qdrant:6333")),
        storage=StorageConfig(download_timeout=60),
        api=ApiConfig(index_timeout=20),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=config)))
    req = FileIndexRequest(presigned_url="https://source/a", s3_url="s3://bucket/a.txt", file_id="same-id")

    with pytest.raises(UpstreamServiceError) as error:
        getattr(files, endpoint)(request, req, object())
    assert error.value.status_code == 504
    assert error.value.retryable is False
    assert writes == []
    assert deadline.request_timeout(60) == 60
