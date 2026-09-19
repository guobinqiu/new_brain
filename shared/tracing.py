from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar, Token
from typing import Callable

from fastapi import FastAPI, Request


TRACEPARENT_PATTERN = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_traceparent: ContextVar[str | None] = ContextVar("traceparent", default=None)


def new_traceparent(trace_id: str | None = None) -> str:
    tid = trace_id if trace_id and re.fullmatch(r"[0-9a-f]{32}", trace_id) else uuid.uuid4().hex
    return f"00-{tid}-{uuid.uuid4().hex[:16]}-01"


def set_traceparent(value: str | None) -> Token:
    if value and TRACEPARENT_PATTERN.fullmatch(value):
        traceparent = value
    else:
        traceparent = new_traceparent()
    return _traceparent.set(traceparent)


def reset_traceparent(token: Token) -> None:
    _traceparent.reset(token)


def get_traceparent() -> str | None:
    return _traceparent.get()


def ensure_traceparent() -> str:
    value = get_traceparent()
    if value:
        return value
    value = new_traceparent()
    _traceparent.set(value)
    return value


def trace_headers() -> dict[str, str]:
    return {"traceparent": ensure_traceparent()}


def trace_id_from_traceparent(value: str | None) -> str | None:
    if not value:
        return None
    match = TRACEPARENT_PATTERN.fullmatch(value)
    return match.group(1) if match else None


def get_trace_id() -> str:
    return trace_id_from_traceparent(ensure_traceparent()) or "-"


def install_trace_middleware(app: FastAPI, *, service_name: str) -> None:
    app.state.service_name = service_name
    logger = logging.getLogger("brain.trace")

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next: Callable):
        incoming = request.headers.get("traceparent")
        token = set_traceparent(incoming)
        traceparent = ensure_traceparent()
        trace_id = trace_id_from_traceparent(traceparent)
        request.state.trace_id = trace_id
        request.state.traceparent = traceparent
        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["traceparent"] = traceparent
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "service request",
                extra={
                    "event": "service_request",
                    "service": service_name,
                    "method": request.method,
                    "path": request.url.path,
                    "trace_id": trace_id,
                    "elapsed_ms": elapsed_ms,
                },
            )
            reset_traceparent(token)
