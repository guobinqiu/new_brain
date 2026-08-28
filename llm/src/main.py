from dotenv import load_dotenv

# load_dotenv() 必须在读 env 的模块导入前调用 —— config.py 走 pydantic-settings
# 直接读 os.environ，无法 import-time 延后；这是 FastAPI 标准 .env 加载 pattern。
load_dotenv()  # noqa: E402

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from openai import APIConnectionError, APIStatusError, RateLimitError  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from llm.src.agent.graphs.chat import build_chat_graph  # noqa: E402
from llm.src.agent.nodes.llm import init_semaphore  # noqa: E402
from llm.src.agent.registry import register_graph, registered_names, set_checkpointer  # noqa: E402
from llm.src.api.auth import close_auth_pool  # noqa: E402
from llm.src.api.middleware import limiter, log_requests  # noqa: E402
from llm.src.api.routes import chat as chat_routes  # noqa: E402
from llm.src.api.routes import health as health_routes  # noqa: E402
from llm.src.api.routes import threads as thread_routes  # noqa: E402
from llm.src.config import settings  # noqa: E402
from llm.src.infra.database import close_pool, init_pool  # noqa: E402
from llm.src.infra.logger import configure_logging, get_logger  # noqa: E402
from llm.src.rag.client import get_rag_client  # noqa: E402

configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_semaphore(settings.llm_concurrency_limit)
    await init_pool()

    checkpoint_pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await checkpoint_pool.open(wait=True, timeout=30)

    # RAG client 单例：构造真实 HTTP 客户端
    rag = get_rag_client()
    logger.info("rag client initialized", base_url=settings.rag_base_url)

    rag_client_for_lifespan = rag

    try:
        checkpointer = AsyncPostgresSaver(checkpoint_pool)
        await checkpointer.setup()
        set_checkpointer(checkpointer)

        # 注册 chat graph（pre-fetch 架构，无需 llm_with_tools）
        register_graph("chat", build_chat_graph(checkpointer))

        # 启动 checkpoint 垃圾回收（删除长时间无活动的会话）
        if settings.checkpoint_gc_enabled:
            from llm.src.api.checkpoint_gc import shutdown_gc, start_gc_loop
            start_gc_loop()

        logger.info("graphs registered", graphs=registered_names())
        yield

        if settings.checkpoint_gc_enabled:
            from llm.src.api.checkpoint_gc import shutdown_gc
            await shutdown_gc()
    finally:
        try:
            await rag_client_for_lifespan.aclose()
        except Exception as e:
            # lifespan 关闭阶段失败不应抛错阻断 shutdown —— 仅记录以便排障
            logger.debug("rag aclose failed at shutdown", error=str(e)[:200])
        await close_auth_pool()
        await checkpoint_pool.close()
    await close_pool()
    logger.info("agent shutdown")


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
    from llm.src.infra.logger import get_trace_id
    logger.warning("rate limit exceeded", detail=str(exc.detail))
    return JSONResponse(
        status_code=429,
        content={"error": "请求过于频繁，请稍后重试"},
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
        content={"error": "输入参数不合法", "details": errors}
    )


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError):
    logger.error("llm rate limited", exc_info=exc)
    return JSONResponse(status_code=429, content={"error": "服务繁忙，请稍后重试"})


@app.exception_handler(APIStatusError)
async def api_status_handler(request: Request, exc: APIStatusError):
    logger.error("llm api error", status_code=exc.status_code, exc_info=exc)
    return JSONResponse(status_code=502, content={"error": "AI 服务暂时不可用"})


@app.exception_handler(APIConnectionError)
async def connection_handler(request: Request, exc: APIConnectionError):
    logger.error("llm connection failed", exc_info=exc)
    return JSONResponse(status_code=503, content={"error": "网络连接异常"})


@app.exception_handler(Exception)
async def general_handler(request: Request, exc: Exception):
    logger.error("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "服务内部错误"})


# ─────────────────────────────────────
# 路由注册
# ─────────────────────────────────────
app.include_router(chat_routes.router)
app.include_router(health_routes.router)
app.include_router(thread_routes.router)
