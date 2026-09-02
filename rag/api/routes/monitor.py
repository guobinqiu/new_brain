from fastapi import APIRouter, Depends, Header

from rag.api.services.auth import require_jwt
from rag.api.services import monitor as service


router = APIRouter()


@router.get("/api/open/rag/monitor")
def monitor(principal=Depends(require_jwt)):
    return service.monitor(principal)


@router.get("/api/open/rag/nodes/monitor")
async def nodes_monitor(authorization: str | None = Header(None), principal=Depends(require_jwt)):
    return await service.nodes_monitor(authorization, principal)
