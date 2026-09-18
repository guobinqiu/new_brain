from fastapi import APIRouter, Depends, Request

from services.rag.core.api.rate_limit import require_rate_limit
from services.rag.core.api.services.auth import require_jwt, require_principal
from services.rag.core.api.schemas import DebugEncodeRequest, DebugSearchRequest, SearchRequest
from services.rag.core.api.services import search as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.post("/api/v1/rag/search")
def open_search(request: Request, req: SearchRequest, principal=Depends(require_principal)):
    return service.search(request.app.state, req, principal)


@router.post("/api/rag/search")
def search(request: Request, req: SearchRequest, principal=Depends(require_jwt)):
    return service.search(request.app.state, req, principal)


@router.post("/api/rag/apps/{app_id}/debug/dense-encode")
def debug_dense_encode(request: Request, app_id: str, req: DebugEncodeRequest, principal=Depends(require_jwt)):
    return service.debug_dense_encode(request.app.state, app_id, req, principal)


@router.post("/api/rag/apps/{app_id}/debug/dense-search")
def debug_dense_search(request: Request, app_id: str, req: DebugSearchRequest, principal=Depends(require_jwt)):
    return service.debug_dense_search(request.app.state, app_id, req, principal)
