from fastapi import APIRouter, Depends, Header

from api.services.auth import require_jwt
from api.services import config as service


router = APIRouter()


@router.get("/api/config")
def get_config(principal=Depends(require_jwt)):
    return service.get_config(principal)


@router.get("/api/nodes/config")
async def nodes_config(authorization: str | None = Header(None), principal=Depends(require_jwt)):
    return await service.nodes_config(authorization, principal)
