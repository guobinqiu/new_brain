from fastapi import APIRouter, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.services.auth import require_jwt
from services.rag.core.api.services import logs as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.get("/api/rag/logs")
async def logs(
    request: Request,
    node_id: str | None = None,
    container: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    principal=Depends(require_jwt),
):
    return await service.logs(request.app.state, node_id, container, start, end, limit, principal)


@router.get("/api/rag/logs/labels/{label}")
async def log_label_values(request: Request, label: str, principal=Depends(require_jwt)):
    return await service.log_label_values(request.app.state, label, principal)
