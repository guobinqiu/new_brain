from fastapi import APIRouter, Depends

from api.services.auth import require_jwt
from api.services import logs as service


router = APIRouter()


@router.get("/api/logs")
async def logs(
    node_id: str | None = None,
    container: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    principal=Depends(require_jwt),
):
    return await service.logs(node_id, container, start, end, limit, principal)


@router.get("/api/logs/labels/{label}")
async def log_label_values(label: str, principal=Depends(require_jwt)):
    return await service.log_label_values(label, principal)
