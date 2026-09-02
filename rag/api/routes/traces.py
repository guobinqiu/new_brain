from fastapi import APIRouter, Depends

from rag.api.services.auth import require_jwt
from rag.api.services import traces as service


router = APIRouter()


@router.get("/api/open/rag/traces")
async def traces(
    app_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    principal=Depends(require_jwt),
):
    return await service.traces(app_id, start, end, limit, principal)
