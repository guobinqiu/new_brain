from fastapi import APIRouter, Depends

from rag.api.rate_limit import require_rate_limit
from rag.api.services.auth import require_principal
from rag.api.schemas import DebugEncodeRequest, DebugSearchRequest, SearchRequest
from rag.api.services import search as service


router = APIRouter()


@router.post("/api/open/rag/search", dependencies=[Depends(require_rate_limit)])
def search(req: SearchRequest, principal=Depends(require_principal)):
    return service.search(req, principal)


@router.post("/api/open/rag/apps/{app_id}/debug/dense-encode")
def debug_dense_encode(app_id: str, req: DebugEncodeRequest, principal=Depends(require_principal)):
    return service.debug_dense_encode(app_id, req, principal)


@router.post("/api/open/rag/apps/{app_id}/debug/sparse-encode")
def debug_sparse_encode(app_id: str, req: DebugEncodeRequest, principal=Depends(require_principal)):
    return service.debug_sparse_encode(app_id, req, principal)


@router.post("/api/open/rag/apps/{app_id}/debug/dense-search")
def debug_dense_search(app_id: str, req: DebugSearchRequest, principal=Depends(require_principal)):
    return service.debug_dense_search(app_id, req, principal)


@router.post("/api/open/rag/apps/{app_id}/debug/sparse-search")
def debug_sparse_search(app_id: str, req: DebugSearchRequest, principal=Depends(require_principal)):
    return service.debug_sparse_search(app_id, req, principal)
