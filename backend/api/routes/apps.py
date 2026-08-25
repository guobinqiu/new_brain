from fastapi import APIRouter, Depends

from api.services.auth import require_jwt
from api.schemas import AppCreateRequest
from api.services import apps as service


router = APIRouter()


@router.get("/api/apps")
def list_apps(principal=Depends(require_jwt)):
    return service.list_apps(principal)


@router.post("/api/apps", status_code=201)
def create_app(req: AppCreateRequest, principal=Depends(require_jwt)):
    return service.create_app(req, principal)


@router.delete("/api/apps/{app_id}")
def delete_app(app_id: str, principal=Depends(require_jwt)):
    return service.delete_app(app_id, principal)


@router.post("/api/apps/{app_id}/database")
def initialize_app_database(app_id: str, principal=Depends(require_jwt)):
    return service.initialize_app_database(app_id, principal)


@router.get("/api/apps/{app_id}/database")
def app_database_status(app_id: str, principal=Depends(require_jwt)):
    return service.app_database_status(app_id, principal)


@router.delete("/api/apps/{app_id}/database")
def delete_app_database(app_id: str, principal=Depends(require_jwt)):
    return service.delete_app_database(app_id, principal)
