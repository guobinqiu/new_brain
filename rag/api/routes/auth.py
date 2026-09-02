from fastapi import APIRouter

from rag.api.schemas import LoginRequest
from rag.api.services import auth as service


router = APIRouter()


@router.post("/api/open/rag/login")
def login(req: LoginRequest):
    return service.login(req)
