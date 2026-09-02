from fastapi import APIRouter, Depends

from rag.api.rate_limit import require_rate_limit
from rag.api.services.auth import require_principal
from rag.api.schemas import SearchRequest
from rag.api.services import search as service


router = APIRouter()


@router.post("/api/open/rag/search", dependencies=[Depends(require_rate_limit)])
def search(req: SearchRequest, principal=Depends(require_principal)):
    return service.search(req, principal)
