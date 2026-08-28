"""api/routes/health.py: GET /health."""

from fastapi import APIRouter

from llm.src.api.middleware import limiter
from llm.src.infra.logger import get_logger

logger = get_logger("api.health")
router = APIRouter()


@router.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}
