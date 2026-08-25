from fastapi import APIRouter, Depends, Header

from api.services.auth import require_jwt
from api.services import monitor as service


router = APIRouter()


@router.get("/api/monitor")
def monitor(principal=Depends(require_jwt)):
    return service.monitor(principal)


@router.get("/api/nodes/monitor")
async def nodes_monitor(authorization: str | None = Header(None), principal=Depends(require_jwt)):
    return await service.nodes_monitor(authorization, principal)
