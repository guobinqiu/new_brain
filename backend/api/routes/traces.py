from fastapi import APIRouter, Depends

from api.services.auth import require_jwt
from api.services import traces as service


router = APIRouter()


@router.get("/api/traces")
async def traces(
    app_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    principal=Depends(require_jwt),
):
    return await service.traces(app_id, start, end, limit, principal)
