from fastapi import APIRouter, Depends, Header

from rag.api.services.auth import require_jwt
from rag.api.services import config as service


router = APIRouter()


@router.get("/api/open/rag/config")
def get_config(principal=Depends(require_jwt)):
    return service.get_config(principal)


@router.get("/api/open/rag/nodes/config")
async def nodes_config(authorization: str | None = Header(None), principal=Depends(require_jwt)):
    return await service.nodes_config(authorization, principal)
