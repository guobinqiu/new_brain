from fastapi import APIRouter, Body, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.services.auth import require_jwt
from services.rag.core.api.schemas import AppCreateRequest
from services.rag.core.api.services import apps as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.get("/api/rag/apps")
def list_apps(request: Request, principal=Depends(require_jwt)):
    return service.list_apps(request.app.state, principal)


@router.post("/api/rag/apps", status_code=201)
def create_app(req: AppCreateRequest, request: Request, principal=Depends(require_jwt)):
    return service.create_app(request.app.state, req, principal)


@router.get("/api/rag/apps/{app_id}/presign-config")
def get_presign_config(app_id: str, request: Request, principal=Depends(require_jwt)):
    return service.get_presign_config(request.app.state, app_id)


@router.put("/api/rag/apps/{app_id}/presign-config")
def set_presign_config(app_id: str, request: Request, template: str = Body(..., media_type="text/plain"), principal=Depends(require_jwt)):
    return service.set_presign_config(request.app.state, app_id, template)


@router.delete("/api/rag/apps/{app_id}")
def delete_app(app_id: str, request: Request, principal=Depends(require_jwt)):
    return service.delete_app(request.app.state, app_id, principal)


@router.post("/api/rag/apps/{app_id}/database")
def initialize_app_database(app_id: str, request: Request, principal=Depends(require_jwt)):
    return service.initialize_app_database(request.app.state, app_id, principal)


@router.get("/api/rag/apps/{app_id}/database")
def app_database_status(app_id: str, request: Request, principal=Depends(require_jwt)):
    return service.app_database_status(request.app.state, app_id, principal)


@router.delete("/api/rag/apps/{app_id}/database")
def delete_app_database(app_id: str, request: Request, principal=Depends(require_jwt)):
    return service.delete_app_database(request.app.state, app_id, principal)
