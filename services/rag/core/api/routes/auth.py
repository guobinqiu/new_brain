from fastapi import APIRouter, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.schemas import LoginRequest
from services.rag.core.api.services import auth as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.post("/api/rag/login")
def login(req: LoginRequest, request: Request):
    return service.login(request.app.state, req)
