from fastapi import HTTPException

from services.rag.core.api.schemas import AppCreateRequest
from services.rag.core.api.services.common import app_database_status as build_app_database_status
from services.rag.core.api.services.common import require_ready
from services.rag.core.presign import build_request, render_config


def list_apps(state, _):
    credentials = state.db_client.list_apps() if state.db_client is not None else state.config.auth.apps
    return {
        "apps": [
            {
                "app_id": app_credential.app_id,
                "api_key": app_credential.api_key,
            }
            for app_credential in credentials
        ]
    }


def create_app(state, req: AppCreateRequest, _):
    if state.db_client is None:
        raise HTTPException(503, "app creation is unavailable without a metadata database")
    try:
        credential = state.db_client.create_app(req.app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"app_id": credential.app_id, "api_key": credential.api_key}


def delete_app(state, app_id: str, _):
    if state.db_client is None:
        raise HTTPException(503, "app deletion is unavailable without a metadata database")
    try:
        deleted = state.db_client.delete_app(app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "app not found")
    return {"app_id": app_id, "deleted": True}


def get_presign_config(state, app_id: str):
    if state.db_client is None:
        raise HTTPException(503, "presign configuration is unavailable without a metadata database")
    template = state.db_client.get_presign_config(app_id)
    if template is None:
        raise HTTPException(404, "app not found")
    return {"presign_config": template}


def set_presign_config(state, app_id: str, template: str):
    if state.db_client is None:
        raise HTTPException(503, "presign configuration is unavailable without a metadata database")
    variables = {"app_id": app_id, "file_id": "file-id", "s3_url": "s3://bucket/file", "filename": "file.pdf"}
    try:
        build_request(template, variables)
        config = render_config(template, variables)
        if not isinstance(config["response_url_path"], str):
            raise ValueError("response_url_path must be a string")
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    if not state.db_client.set_presign_config(app_id, template):
        raise HTTPException(404, "app not found")
    return {"presign_config": template}


def initialize_app_database(state, app_id: str, _):
    require_ready(state)
    try:
        state.vector_client.ensure_app_collection(app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"app_id": app_id, "initialized": True}


def app_database_status(state, app_id: str, _):
    require_ready(state)
    return build_app_database_status(state, app_id)


def delete_app_database(state, app_id: str, _):
    require_ready(state)
    status = build_app_database_status(state, app_id)
    if not status["exists"]:
        raise HTTPException(404, "app database not found")
    deleted = state.vector_client.drop_app_collection(app_id)
    if state.db_client is not None:
        state.db_client.purge_app(app_id)
    return {"app_id": app_id, "deleted": deleted}
