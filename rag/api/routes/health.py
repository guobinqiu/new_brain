from fastapi import APIRouter

from rag.api.services import health as service


router = APIRouter()


@router.get("/api/health")
def health():
    return service.health()


@router.get("/api/ready")
def ready():
    return service.ready()
