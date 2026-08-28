from fastapi import APIRouter

from rag.api.schemas import LoginRequest
from rag.api.services import auth as service


router = APIRouter()


@router.post("/api/login")
def login(req: LoginRequest):
    return service.login(req)
