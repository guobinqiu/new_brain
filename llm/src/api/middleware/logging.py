import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse

from llm.src.config import settings
from llm.src.infra.logger import get_logger, log_perf, set_trace_id
from llm.src.infra.metrics import Timer

logger = get_logger("middleware")

async def log_requests(request: Request, call_next):
    trace_id = set_trace_id()

    try:
        with Timer() as t:
            # 整个请求最多等 settings.request_timeout_s 秒
            response = await asyncio.wait_for(
                call_next(request),
                timeout=settings.request_timeout_s
            )

        response.headers["X-Trace-Id"] = trace_id
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

    except TimeoutError:
        logger.error(
            "request timeout",
            method=request.method,
            path=request.url.path,
            timeout_s=settings.request_timeout_s,
        )
        return JSONResponse(
            status_code=504,
            content={"error": "请求超时，请稍后重试"},
            headers={"X-Trace-Id": trace_id}
        )
