from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pymilvus.exceptions import MilvusException

from services.rag.app.main import app as rag_app
from services.rag.core.api.routes.files import router
from services.rag.core.api.services.auth import require_jwt, require_principal
from services.rag.core.auth import Principal
from services.rag.core.scope import app_collection
from services.rag.tests.e2e.test_index_failure_http import http_server
from shared.config import ApiConfig, StorageConfig
from shared.tracing import install_trace_middleware


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("prefix", ["/api/rag", "/api/v1/rag"])
def test_delete_sdk_error_reaches_http_response(prefix):
    error = MilvusException(code=8, message="rate limit exceeded[rate=0.05]")

    class Vector:
        def app_collection_exists(self, app_id):
            return True

        def app_scope(self, app_id):
            return app_collection(app_id)

        def delete_file_chunks(self, file_id):
            raise error

    app = FastAPI(exception_handlers=rag_app.exception_handlers)
    app.include_router(router)
    install_trace_middleware(app, service_name="rag")
    principal = Principal(type="app", app_id="tenant")
    app.dependency_overrides[require_jwt] = lambda: principal
    app.dependency_overrides[require_principal] = lambda: principal
    app.state.ready = True
    app.state.vector_client = Vector()
    app.state.db_client = None
    app.state.config = SimpleNamespace(api=ApiConfig(), storage=StorageConfig(endpoint_url="http://unused:9000"))
    traceparent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    with http_server(app) as url:
        response = httpx.delete(url + prefix + "/files/original", headers={"traceparent": traceparent})
    assert response.status_code == 500
    assert response.json() == {
        "success": False, "error": str(error), "retryable": False,
        "traceId": "a" * 32, "file_id": "original",
    }
    assert response.headers["traceparent"] == traceparent
