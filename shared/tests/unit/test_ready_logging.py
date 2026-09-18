import asyncio
import json
import logging
from io import StringIO

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from shared.config import LoggingConfig
from shared.logging_config import configure_logging


@pytest.mark.parametrize("status", [200, 503])
def test_ready_request_logs_are_silent_but_business_requests_remain(status):
    stream = StringIO()
    configure_logging(LoggingConfig(), stream=stream)
    access = logging.getLogger("uvicorn.access")
    client = logging.getLogger("httpx")
    trace = logging.getLogger("brain.trace")
    for path in ("/ready", "/ready?probe=1"):
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1234", "GET", path, "1.1", status)
        client.info('HTTP Request: %s %s "%s %d %s"', "GET", httpx.URL("http://parser:7000" + path), "HTTP/1.1", status, "OK")
        trace.info("service request", extra={"event": "service_request", "path": "/ready"})
    assert stream.getvalue() == ""

    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1234", "POST", "/v1/embeddings", "1.1", 200)
    client.info('HTTP Request: %s %s "%s %d %s"', "POST", httpx.URL("https://ark.example/responses"), "HTTP/1.1", 200, "OK")
    trace.info("service request", extra={"event": "service_request", "path": "/api/v1/rag/search"})
    logging.getLogger("services.parser").error("parser initialization failed")
    assert len(stream.getvalue().splitlines()) == 4


def test_not_ready_response_is_preserved_without_exception_log():
    from shared.api_errors import http_exception_handler

    stream = StringIO()
    configure_logging(LoggingConfig(), stream=stream)
    request = Request({"type": "http", "method": "GET", "path": "/ready", "headers": [], "app": FastAPI()})
    response = asyncio.run(http_exception_handler(request, HTTPException(503, "model is loading")))
    assert response.status_code == 503
    assert json.loads(response.body)["error"] == "model is loading"
    assert stream.getvalue() == ""
