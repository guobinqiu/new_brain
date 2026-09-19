import asyncio
import json

from fastapi import FastAPI, Request


def test_unhandled_error_preserves_error_and_request_trace(caplog):
    from shared.api_errors import unhandled_exception_handler
    from shared.tracing import install_trace_middleware

    app = FastAPI()
    install_trace_middleware(app, service_name="rag")
    request = Request({
        "type": "http", "method": "DELETE", "path": "/api/rag/files/original",
        "headers": [], "app": app, "path_params": {"file_id": "original"},
        "state": {"trace_id": "a" * 32, "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"},
    })
    response = asyncio.run(unhandled_exception_handler(request, RuntimeError("rate limit exceeded[rate=0.05]")))
    assert response.status_code == 500
    assert json.loads(response.body) == {
        "success": False, "error": "rate limit exceeded[rate=0.05]",
        "service": "rag", "retryable": False, "traceId": "a" * 32, "file_id": "original",
    }
    assert response.headers["traceparent"] == request.state.traceparent
    assert caplog.records[-1].exc_info is not None
