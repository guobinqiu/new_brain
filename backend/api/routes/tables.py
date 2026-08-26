from fastapi import APIRouter, Depends

from api.schemas import AdminTablePartsRequest, TablePartsRequest
from api.services import tables as service
from api.services.auth import require_aksk, require_jwt


router = APIRouter()


@router.post("/api/open/tables/parts")
def client_table_parts(req: TablePartsRequest, principal=Depends(require_aksk)):
    return service.client_table_parts(req, principal)


@router.post("/api/tables/parts")
def table_parts(req: AdminTablePartsRequest, principal=Depends(require_jwt)):
    return service.table_parts(req, principal)
