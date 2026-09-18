from __future__ import annotations

import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

from shared.api_errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from shared.config import LoggingConfig
from shared.logging_config import configure_logging
from shared.tracing import install_trace_middleware

from services.ops.app.auth import require_admin_jwt
from services.ops.app.config_manager import ConfigManager
from services.ops.app.docker_engine import DockerEngineClient
from services.ops.app.swarm_manager import SwarmManager


class ConfigUpdate(BaseModel):
    content: str


class ConfigApplyRequest(BaseModel):
    name: str


class ServiceScaleRequest(BaseModel):
    service: str
    replicas: int = Field(ge=0)


def create_app(*, services=None, configs=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(LoggingConfig())
        yield
        close = getattr(getattr(app.state.services, "docker", None), "close", None)
        if close is not None:
            close()

    app = FastAPI(title="Brain Ops API", lifespan=lifespan)
    install_trace_middleware(app, service_name="ops")
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    project_root = Path(os.getenv("APP_PROJECT_ROOT", "/app"))
    app.state.services = services or SwarmManager(
        DockerEngineClient(),
        stack=os.getenv("STACK", "brain"),
        ctrl_stack=os.getenv("CTRL_STACK", "brain_ctrl"),
        project_root=project_root,
        host_project_root=os.getenv("HOST_PROJECT_ROOT"),
    )
    app.state.configs = configs or ConfigManager(project_root)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    @app.get("/api/ops/services", dependencies=[Depends(require_admin_jwt)])
    def list_services():
        return {"services": app.state.services.list_services()}

    @app.post("/api/ops/services/{service}/start", dependencies=[Depends(require_admin_jwt)])
    def start_service(service: str):
        return _service_action(lambda: app.state.services.start(service))

    @app.post("/api/ops/services/{service}/stop", dependencies=[Depends(require_admin_jwt)])
    def stop_service(service: str):
        return _service_action(lambda: app.state.services.stop(service))

    @app.post("/api/ops/services/scale", dependencies=[Depends(require_admin_jwt)])
    def scale_service(request: ServiceScaleRequest):
        return _service_action(lambda: app.state.services.scale(request.service, request.replicas))

    @app.post("/api/ops/services/{service}/rollout", dependencies=[Depends(require_admin_jwt)])
    def rollout_service(service: str):
        return _service_action(lambda: app.state.services.rollout(service))

    @app.get("/api/ops/services/{service}/tasks", dependencies=[Depends(require_admin_jwt)])
    def service_tasks(service: str):
        return _service_action(lambda: {"tasks": app.state.services.list_tasks(service)})

    @app.get("/api/ops/services/{service}/logs", dependencies=[Depends(require_admin_jwt)])
    def service_logs(service: str, tail: int = Query(50, ge=1, le=500)):
        return _service_action(lambda: {"logs": app.state.services.logs(service, tail=tail)})

    @app.get("/api/ops/nodes", dependencies=[Depends(require_admin_jwt)])
    def list_nodes():
        return {"nodes": app.state.services.list_nodes()}

    @app.get("/api/ops/swarm/join-command", dependencies=[Depends(require_admin_jwt)])
    def join_command(role: str = Query("worker", pattern="^(worker|manager)$")):
        return _service_action(lambda: {"role": role, "command": app.state.services.join_command(role)})

    @app.post("/api/ops/stack/deploy", dependencies=[Depends(require_admin_jwt)])
    def deploy_stack():
        return _service_action(lambda: app.state.services.deploy_stack())

    @app.post("/api/ops/stack/remove", dependencies=[Depends(require_admin_jwt)])
    def remove_stack():
        return _service_action(lambda: app.state.services.remove_stack())

    @app.get("/api/ops/configs", dependencies=[Depends(require_admin_jwt)])
    def list_configs():
        return {"configs": app.state.configs.list()}

    @app.get("/api/ops/configs/{name}", dependencies=[Depends(require_admin_jwt)])
    def read_config(name: str):
        return _config_action(lambda: _config_payload(app.state.configs.read(name)))

    @app.post("/api/ops/configs/{name}/validate", dependencies=[Depends(require_admin_jwt)])
    def validate_config(name: str, update: ConfigUpdate):
        return _config_action(lambda: _validated(app.state.configs, name, update.content))

    @app.put("/api/ops/configs/{name}", dependencies=[Depends(require_admin_jwt)])
    def write_config(name: str, update: ConfigUpdate):
        return _config_action(lambda: _config_payload(app.state.configs.write(name, update.content)))

    @app.post("/api/ops/configs/apply", dependencies=[Depends(require_admin_jwt)])
    def apply_config(request: ConfigApplyRequest):
        return _config_action(lambda: _apply_config(app.state.configs, app.state.services, request.name))

    return app


def _validated(configs, name: str, content: str) -> dict:
    configs.validate(name, content)
    return {"valid": True}


def _config_payload(config) -> dict:
    return {
        "name": config.name,
        "path": config.path,
        "service": config.service,
        "content": config.content,
        "deploy_required": config.requires_deploy,
    }


def _apply_config(configs, services, name: str) -> dict:
    config = configs.read(name)
    payload = _config_payload(config)
    if config.service:
        payload["rollout"] = services.rollout(config.service)
        payload["deploy_required"] = False
    else:
        payload["deploy"] = services.deploy_stack()
        payload["deploy_required"] = False
    return payload


def _service_action(operation):
    try:
        return operation()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(503, str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(503, exc.stderr or exc.stdout or str(exc)) from exc


def _config_action(operation):
    try:
        return operation()
    except KeyError as exc:
        raise HTTPException(404, f"unknown config: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(503, str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(503, exc.stderr or exc.stdout or str(exc)) from exc


app = create_app()
