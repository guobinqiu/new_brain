from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from openai import APIConnectionError, APIStatusError, RateLimitError  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from shared.api_errors import unhandled_exception_handler  # noqa: E402

from services.llm.src.agent.graphs.chat import build_chat_graph  # noqa: E402
from services.llm.src.agent.nodes.llm import init_semaphore  # noqa: E402
from services.llm.src.agent.registry import register_graph, registered_names, set_checkpointer  # noqa: E402
from services.llm.src.api.auth import close_auth_pool  # noqa: E402
from services.llm.src.api.middleware import limiter, log_requests  # noqa: E402
from services.llm.src.api.routes import chat as chat_routes  # noqa: E402
from services.llm.src.api.routes import health as health_routes  # noqa: E402
from services.llm.src.api.routes import threads as thread_routes  # noqa: E402
from services.llm.src.config import settings  # noqa: E402
from services.llm.src.infra.logger import configure_logging, get_logger  # noqa: E402
from services.llm.src.rag.client import get_rag_client  # noqa: E402

configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_semaphore(settings.llm_concurrency_limit)

    # RAG client 单例：构造真实 HTTP 客户端
    rag = get_rag_client()
    logger.info("rag client initialized", base_url=settings.rag_base_url)

    rag_client_for_lifespan = rag
    checkpointer_cm = None

    try:
        checkpointer_cm, checkpointer = await _create_checkpointer()
        set_checkpointer(checkpointer)

        # 注册 chat graph（pre-fetch 架构，无需 llm_with_tools）
        register_graph("chat", build_chat_graph(checkpointer))

        logger.info("graphs registered", graphs=registered_names())
        yield
    finally:
        if checkpointer_cm is not None:
            await checkpointer_cm.__aexit__(None, None, None)
        try:
            await rag_client_for_lifespan.aclose()
        except Exception as e:
            # lifespan 关闭阶段失败不应抛错阻断 shutdown —— 仅记录以便排障
            logger.debug("rag aclose failed at shutdown", error=str(e)[:200])
        close_auth_pool()
    logger.info("agent shutdown")


async def _create_checkpointer():
    checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
    try:
        checkpointer = await checkpointer_cm.__aenter__()
        await checkpointer.setup()
    except Exception:
        await checkpointer_cm.__aexit__(None, None, None)
        raise
    logger.info("postgres checkpointer initialized")
    return checkpointer_cm, checkpointer


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(log_requests)


# ─────────────────────────────────────
# 异常处理
# ─────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    from services.llm.src.infra.logger import get_trace_id
    logger.warning("rate limit exceeded", detail=str(exc.detail))
    return JSONResponse(
        status_code=429,
        content={"error": str(exc.detail)},
        headers={
            "Retry-After": str(exc.detail),
            "X-Trace-Id": get_trace_id(),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": e["loc"][-1], "msg": e["msg"]}
        for e in exc.errors()
    ]
    logger.warning("validation failed", errors=errors)
    return JSONResponse(
        status_code=422,
        content={"error": str(exc), "details": errors}
    )


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError):
    logger.error("llm rate limited", exc_info=exc)
    return JSONResponse(status_code=429, content={"error": str(exc)})


@app.exception_handler(APIStatusError)
async def api_status_handler(request: Request, exc: APIStatusError):
    logger.error("llm api error", status_code=exc.status_code, exc_info=exc)
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.exception_handler(APIConnectionError)
async def connection_handler(request: Request, exc: APIConnectionError):
    logger.error("llm connection failed", exc_info=exc)
    return JSONResponse(status_code=503, content={"error": str(exc)})


@app.exception_handler(Exception)
async def general_handler(request: Request, exc: Exception):
    return await unhandled_exception_handler(request, exc)


# ─────────────────────────────────────
# 路由注册
# ─────────────────────────────────────
app.include_router(chat_routes.router)
app.include_router(health_routes.router)
app.include_router(thread_routes.router)
