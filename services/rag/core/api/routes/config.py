from fastapi import APIRouter, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.services.auth import require_jwt
from services.rag.core.api.services import config as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.get("/api/rag/config")
def get_config(request: Request, principal=Depends(require_jwt)):
    return service.get_config(request.app.state, principal)
