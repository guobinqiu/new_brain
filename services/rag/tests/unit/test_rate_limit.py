import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(headers: list[tuple[bytes, bytes]], client: tuple[str, int] = ("10.0.0.1", 1234)) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/v1/rag/search",
        "headers": headers,
        "client": client,
    })


def _route(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route
    raise AssertionError(f"route not found: {method} {path}")


def _dependency_names(route) -> set[str]:
    return {dependency.call.__name__ for dependency in route.dependant.dependencies}


def test_get_key_uses_forwarded_for_value():
    from services.rag.core.api.rate_limit import _get_key

    request = _request([(b"x-forwarded-for", b"1.1.1.1")])

    assert _get_key(request) == "1.1.1.1"


def test_get_key_does_not_trust_first_forwarded_for_segment():
    from services.rag.core.api.rate_limit import _get_key

    request = _request([(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")])

    assert _get_key(request) == "1.1.1.1, 2.2.2.2"


def test_get_key_falls_back_to_remote_address():
    from services.rag.core.api.rate_limit import _get_key

    request = _request([])

    assert _get_key(request) == "10.0.0.1"


def test_check_raises_429_after_limit(monkeypatch):
    from services.rag.core.api import rate_limit

    rate_limit.reset_rate_limit()
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: 1.0)
    request = _request([])

    rate_limit._check(request, "1/minute", "test")

    with pytest.raises(HTTPException) as exc:
        rate_limit._check(request, "1/minute", "test")
    assert exc.value.status_code == 429


def test_open_search_uses_default_rate_limit():
    from services.rag.core.api.routes.search import router

    route = _route(router, "/api/v1/rag/search", "POST")

    assert "require_rate_limit" in _dependency_names(route)


def test_all_rag_routes_use_default_rate_limit():
    from services.rag.core.api.routes import (
        apps_router,
        auth_router,
        config_router,
        files_router,
        health_router,
        logs_router,
        search_router,
        traces_router,
    )

    for router in (health_router, auth_router, apps_router, config_router, logs_router, traces_router, files_router, search_router):
        for route in router.routes:
            if not getattr(route, "path", "").startswith("/api/"):
                continue
            assert "require_rate_limit" in _dependency_names(route), route.path


def test_monitor_routes_are_not_registered():
    from fastapi import FastAPI
    from services.rag.core.api.routes import register_routes

    app = FastAPI()
    register_routes(app)

    paths = {getattr(route, "path", "") for route in app.router.routes}
    assert "/api/rag/monitor" not in paths
    assert "/api/rag/nodes/monitor" not in paths


def test_open_sync_index_uses_index_rate_limit():
    from services.rag.core.api.routes.files import router

    route = _route(router, "/api/v1/rag/files", "POST")

    assert "require_rate_limit" in _dependency_names(route)
    assert "require_index_rate_limit" in _dependency_names(route)


def test_admin_upload_uses_index_rate_limit():
    from services.rag.core.api.routes.files import router

    route = _route(router, "/api/rag/upload", "POST")

    assert "require_rate_limit" in _dependency_names(route)
    assert "require_index_rate_limit" in _dependency_names(route)


def test_open_delete_uses_default_rate_limit():
    from services.rag.core.api.routes.files import router

    route = _route(router, "/api/v1/rag/files/{file_id}", "DELETE")

    assert "require_rate_limit" in _dependency_names(route)
