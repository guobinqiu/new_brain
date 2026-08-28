from fastapi import HTTPException

from rag.api.runtime import runtime
from rag.api.schemas import AppCreateRequest
from rag.api.services.common import app_database_status as build_app_database_status
from rag.api.services.common import require_database_ready, require_ready


def list_apps(_):
    require_database_ready()
    return {
        "apps": [
            {
                "app_id": app_credential.app_id,
                "access_key": app_credential.access_key,
                "secret_key": app_credential.secret_key,
            }
            for app_credential in runtime.application.database.list_apps()
        ]
    }


def create_app(req: AppCreateRequest, _):
    require_database_ready()
    try:
        credential = runtime.application.database.create_app(req.app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "app_id": credential.app_id,
        "access_key": credential.access_key,
        "secret_key": credential.secret_key,
    }


def delete_app(app_id: str, _):
    require_database_ready()
    try:
        deleted = runtime.application.database.delete_app(app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "app not found")
    runtime.application.database.purge_app(app_id)
    return {"deleted": True}


def initialize_app_database(app_id: str, _):
    require_ready()
    try:
        runtime.application.store.ensure_app_collection(app_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"app_id": app_id, "initialized": True}


def app_database_status(app_id: str, _):
    require_ready()
    return build_app_database_status(app_id)


def delete_app_database(app_id: str, _):
    require_ready()
    status = build_app_database_status(app_id)
    if not status["exists"]:
        raise HTTPException(404, "app database not found")
    deleted = runtime.application.store.drop_app_collection(app_id)
    runtime.application.database.purge_app(app_id)
    return {"app_id": app_id, "deleted": deleted}
