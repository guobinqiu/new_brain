import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.api_errors import upstream_exception_handler, unhandled_exception_handler

from shared.config import AppConfig
from services.rag.clients.db.postgres import PgClient
from services.rag.clients.inference import HttpInferenceClient
from services.rag.clients.parser import HttpParserClient
from services.rag.clients.vector.milvus import MilvusVectorClient
from services.rag.clients.vector.qdrant import QdrantVectorClient
from services.rag.core.api.routes import register_routes
from services.rag.core.api.index_errors import install_index_error_handlers
from services.rag.core.loader import load_app_config
from shared.logging_config import configure_logging
from services.rag.core.search.pipeline import SearchPipeline
from shared.tracing import install_trace_middleware
from shared.upstream import UpstreamServiceError


logger = logging.getLogger("services.rag")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_app(app, load_app_config())
    configure_logging(app.state.config.logging)
    logger.info("Starting RAG API ...", extra={"event": "startup_start"})
    if app.state.config.database is not None:
        _initialize_database(app)
    logger.info("RAG API startup done", extra={"event": "startup_ready"})
    try:
        yield
    finally:
        _close_clients(app)
        logger.info("RAG API closed", extra={"event": "shutdown"})


app = FastAPI(title="Brain RAG API", lifespan=lifespan)
install_trace_middleware(app, service_name="rag")
install_index_error_handlers(app)


app.add_exception_handler(UpstreamServiceError, upstream_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_routes(app)


@app.get("/health")
def health():
    return {"status": "ok"}


def _configure_app(app: FastAPI, config: AppConfig) -> None:
    if config.services.vector is None:
        raise ValueError("rag vector service is required")

    parser = HttpParserClient(
        config.services.parser.base_url,
        api_key=config.services.parser.api_key,
        timeout=config.services.parser.timeout,
    )
    inference = HttpInferenceClient(
        config.services.inference.base_url,
        api_key=config.services.inference.api_key,
        timeout=config.services.inference.timeout,
        embedding_timeout=config.services.inference.embedding.timeout,
        rerank_timeout=config.services.inference.rerank.timeout,
    )
    try:
        inference.start()
    except Exception:
        parser.close()
        inference.close()
        raise

    vector_backend = config.services.vector.provider
    if vector_backend == "qdrant":
        vector = QdrantVectorClient(
            dense=inference.dense,
            sparse=inference.sparse,
            url=config.services.vector.base_url,
            timeout=config.services.vector.timeout,
            query_timeout=config.services.vector.query_timeout,
            write_timeout=config.services.vector.write_timeout,
            init_timeout=config.services.vector.init_timeout,
            drop_timeout=config.services.vector.drop_timeout,
            quantization=config.services.vector.quantization,
            api_key=config.services.vector.api_key,
            retry=config.services.vector.retry,
        )
    elif vector_backend == "milvus":
        vector = MilvusVectorClient(
            dense=inference.dense,
            sparse=inference.sparse,
            uri=config.services.vector.base_url,
            timeout=config.services.vector.timeout,
            query_timeout=config.services.vector.query_timeout,
            write_timeout=config.services.vector.write_timeout,
            init_timeout=config.services.vector.init_timeout,
            drop_timeout=config.services.vector.drop_timeout,
            token=config.services.vector.token,
            retry=config.services.vector.retry,
        )
    else:
        raise ValueError(f"unsupported vector: {config.services.vector.provider}")

    app.state.config = config
    app.state.config_name = config.name
    app.state.vector_backend = vector_backend
    app.state.db_client = (
        PgClient(url=config.database.url, pool_size=config.database.pool_size)
        if config.database is not None else None
    )
    app.state.parser_client = parser
    app.state.inference_client = inference
    app.state.vector_client = vector
    app.state.search_pipeline = SearchPipeline(vector=vector, rerank=inference.rerank, vector_backend=vector_backend)
    app.state.search_trace = None
    app.state.ready = True


def _initialize_database(app: FastAPI) -> None:
    try:
        app.state.db_client.initialize()
        logger.info("database schema initialized", extra={"event": "database_schema_ready"})
        recovered = app.state.db_client.mark_interrupted_indexing_failed()
        if recovered:
            logger.warning("interrupted indexing files marked failed", extra={"event": "database_indexing_recovered", "file_count": recovered})
    except Exception as exc:
        logger.warning("database schema initialization failed", exc_info=exc, extra={"event": "database_schema_init_failed"})


def _close_clients(app: FastAPI) -> None:
    state = app.state
    for name in ("parser_client", "search_pipeline", "vector_client", "inference_client", "db_client"):
        component = getattr(state, name, None)
        if component is None:
            continue
        close = getattr(component, "close", None)
        if callable(close):
            close()
            continue
        stop = getattr(component, "stop", None)
        if callable(stop):
            stop()
    state.ready = False
