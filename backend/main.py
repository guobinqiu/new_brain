import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.runtime import runtime
from api.routes import register_routes
from logging_config import configure_logging


logger = logging.getLogger("rag.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(runtime.application.config.logging)
    app.state.application = runtime.application
    stop_event = None
    if runtime.startup_in_background:
        stop_event = threading.Event()
        startup_thread = threading.Thread(target=_start_application_until_ready, args=(stop_event,), name="rag-startup", daemon=True)
        startup_thread.start()
    else:
        logger.info("Loading models ...", extra={"event": "startup_load_models"})
        runtime.application.start()
        logger.info("Startup model load done", extra={"event": "startup_ready"})
    runtime.start_index_consumer()
    yield
    runtime.stop_index_consumer()
    if stop_event is not None:
        stop_event.set()
    runtime.application.stop()
    logger.info("Application closed", extra={"event": "shutdown"})


app = FastAPI(title="Qdrant Knowledge Search API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_routes(app)


def _start_application_until_ready(stop_event: threading.Event):
    retry_seconds = 1
    while not stop_event.is_set() and not runtime.application.ready:
        try:
            logger.info("Loading models ...", extra={"event": "startup_load_models"})
            runtime.application.start()
            logger.info("Startup model load done", extra={"event": "startup_ready"})
            return
        except Exception as exc:
            logger.warning(
                "Application startup failed; retrying",
                exc_info=True,
                extra={"event": "startup_retry", "retry_seconds": retry_seconds, "error": str(exc)},
            )
            try:
                runtime.application.stop()
            except Exception:
                logger.exception("Application cleanup after failed startup failed", extra={"event": "startup_cleanup_failed"})
            stop_event.wait(retry_seconds)
            retry_seconds = min(retry_seconds * 2, runtime.startup_retry_max_interval_seconds)
