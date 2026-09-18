from fastapi import APIRouter, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.services.auth import require_jwt
from services.rag.core.api.services import traces as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.get("/api/rag/traces")
async def traces(
    request: Request,
    app_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    principal=Depends(require_jwt),
):
    return await service.traces(request.app.state, app_id, start, end, limit, principal)
