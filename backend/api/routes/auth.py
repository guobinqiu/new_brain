from fastapi import APIRouter

from api.schemas import LoginRequest
from api.services import auth as service


router = APIRouter()


@router.post("/api/login")
def login(req: LoginRequest):
    return service.login(req)
