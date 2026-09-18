import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse

from services.llm.src.config import settings
from services.llm.src.infra.logger import get_logger, log_perf, set_trace_id
from services.llm.src.infra.metrics import Timer

logger = get_logger("middleware")

async def log_requests(request: Request, call_next):
    trace_id = set_trace_id()
    request.state.trace_id = trace_id

    try:
        with Timer() as t:
            # 整个请求最多等 settings.request_timeout 秒
            response = await asyncio.wait_for(
                call_next(request),
                timeout=settings.request_timeout
            )

        response.headers["X-Trace-Id"] = trace_id
        if request.url.path != "/ready":
            log_perf(
                logger,
                "request completed",
                kind="http",
                label=request.url.path,
                total_ms=round(t.ms, 1),
                method=request.method,
                status=response.status_code,
            )
        return response

    except TimeoutError as exc:
        logger.error(
            "request timeout",
            method=request.method,
            path=request.url.path,
            timeout=settings.request_timeout,
        )
        return JSONResponse(
            status_code=504,
            content={"error": str(exc) or repr(exc), "timeout": settings.request_timeout, "traceId": trace_id},
            headers={"X-Trace-Id": trace_id}
        )
