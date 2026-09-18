from fastapi import APIRouter, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.services import health as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.get("/ready")
def ready(request: Request):
    return service.ready(request.app.state)
