import logging
import uuid
from contextvars import ContextVar

import structlog
from shared.logging_config import install_ready_log_filter

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_thread_id: ContextVar[str] = ContextVar("thread_id", default=None)


def set_trace_id(trace_id: str = None) -> str:
    tid = trace_id or uuid.uuid4().hex
    _trace_id.set(tid)
    structlog.contextvars.bind_contextvars(trace_id=tid)
    return tid


def get_trace_id() -> str:
    return _trace_id.get()


def set_thread_id(thread_id: str = None) -> str:
    tid = thread_id
    _thread_id.set(tid)
    structlog.contextvars.bind_contextvars(thread_id=tid)
    return tid


def get_thread_id() -> str:
    return _thread_id.get()


def configure_logging():
    """应用启动时调用一次，配置 structlog + stdlib logging。"""
    from services.llm.src.config import settings

    install_ready_log_filter()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # structlog 处理链
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 让 stdlib logging（uvicorn / tenacity 等第三方库）也输出 JSON
    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(log_t=name, phase="biz")


# ---------------------------------------------------------------------------
# Unified performance / latency logging
# ---------------------------------------------------------------------------
# Every latency-relevant log line goes through `log_perf`. This guarantees:
#   - phase="perf"          → single anchor key to filter all latency lines
#   - kind="<layer>.<op>"   → hierarchy (http / node / llm.call / llm.stream / ...)
#   - label="<caller>"      → logical call site (e.g. "rag_query_done")
#
# All timing fields use consistent names:
#   total_ms             — total wall-clock duration (always present)
#   wait_ms              — time blocked on semaphore / queue
#   llm_ms               — pure LLM time (excludes wait)
#   ttft_ms              — time to first **meaningful** stream payload
#   ttft_first_chunk_ms  — time to first HTTP chunk (may be empty handshake)
#
# Query example:
#   jq 'select(.phase=="perf")'                 # all latency logs
#   jq 'select(.phase=="perf" and .kind=="llm.stream") | .ttft_ms'
# ---------------------------------------------------------------------------
def log_perf(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    *,
    kind: str,
    label: str,
    **timings,
) -> None:
    """Emit a standardized latency log line and persist to DB (best-effort).

    Args:
        logger: a bound logger (usually module-level `get_logger(...)`).
        event: human-readable event name, e.g. "llm stream done".
        kind: hierarchical category, e.g. "llm.stream", "node.parallel", "http".
        label: caller identity, e.g. "validate_extract", "/api/v1/llm/chat/stream".
        **timings: numeric timing fields (total_ms, wait_ms, llm_ms, ttft_ms,
                   ttft_first_chunk_ms, ...) plus any free-form context keys.

    Null/None timings are preserved as-is (so queries can distinguish
    "not applicable" from zero).
    """
    logger.info(event, phase="perf", kind=kind, label=label, **timings)
    # perf_logs DB 持久化已移除（架构 §13.1）：仅保留 stdout JSON 输出
    return
