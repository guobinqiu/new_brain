from fastapi import FastAPI

from rag.api.routes.apps import router as apps_router
from rag.api.routes.auth import router as auth_router
from rag.api.routes.config import router as config_router
from rag.api.routes.health import router as health_router
from rag.api.routes.files import router as files_router
from rag.api.routes.logs import router as logs_router
from rag.api.routes.monitor import router as monitor_router
from rag.api.routes.search import router as search_router
from rag.api.routes.traces import router as traces_router


def register_routes(app: FastAPI) -> None:
    for router in (
        health_router,
        auth_router,
        apps_router,
        config_router,
        monitor_router,
        logs_router,
        traces_router,
        files_router,
        search_router,
    ):
        app.router.routes.extend(router.routes)
