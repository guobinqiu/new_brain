from fastapi import APIRouter, Depends

from api.rate_limit import require_rate_limit
from api.services.auth import require_aksk, require_jwt
from api.schemas import SearchRequest
from api.services import search as service


router = APIRouter()


@router.post("/api/open/search", dependencies=[Depends(require_rate_limit)])
def client_search(req: SearchRequest, principal=Depends(require_aksk)):
    return service.client_search(req, principal)


@router.post("/api/search")
def search(req: SearchRequest, principal=Depends(require_jwt)):
    return service.search(req, principal)
