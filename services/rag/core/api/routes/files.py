from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from shared.deadline import index_deadline

from services.rag.core.api.rate_limit import require_index_rate_limit, require_rate_limit
from services.rag.core.api.services.auth import require_jwt, require_principal
from services.rag.core.api.schemas import BatchIndexRequest, ChunksQueryRequest, FileIndexRequest, PresignRequest, StoredFileIndexRequest
from services.rag.core.api.services import batch_files
from services.rag.core.api.services import files as service


router = APIRouter(dependencies=[Depends(require_rate_limit)])


@router.post("/api/rag/upload", dependencies=[Depends(require_index_rate_limit)])
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    app_id: str = Form(...),
    principal=Depends(require_jwt),
    file_id: str | None = Form(None, min_length=1, max_length=64),
):
    return await service.upload_file(request.app.state, file, app_id, principal, file_id=file_id)


@router.post("/api/rag/files", dependencies=[Depends(require_index_rate_limit)])
def admin_index_file(request: Request, req: FileIndexRequest | StoredFileIndexRequest, principal=Depends(require_jwt)):
    return _index_file(request, req, principal)


@router.post("/api/v1/rag/files", dependencies=[Depends(require_index_rate_limit)])
def open_index_file(request: Request, req: FileIndexRequest, principal=Depends(require_principal)):
    return _index_file(request, req, principal)


@router.post("/api/v1/rag/files/batch", dependencies=[Depends(require_index_rate_limit)])
async def open_batch_index_files(request: Request, req: BatchIndexRequest, principal=Depends(require_principal), authorization: str | None = Header(None)):
    try:
        with index_deadline(request.app.state.config.api.index_timeout):
            if authorization is None:
                raise HTTPException(401, "missing bearer token")
            return await batch_files.index_file(request.app.state, req, principal, authorization)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)


def _index_file(request: Request, req: FileIndexRequest, principal):
    try:
        with index_deadline(request.app.state.config.api.index_timeout):
            return service.index_file(request.app.state, req, principal)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)


@router.post("/api/rag/presign")
def presign_object(request: Request, req: PresignRequest, principal=Depends(require_jwt)):
    return service.presign_object(request.app.state, req, principal)


@router.post("/api/v1/rag/presign")
def open_presign_object(request: Request, req: PresignRequest, principal=Depends(require_principal)):
    return service.client_presign_object(request.app.state, req, principal)


@router.get("/api/rag/files")
def files(request: Request, limit: int = 50, cursor: str | None = None, app_id: str | None = None, principal=Depends(require_jwt)):
    return service.files(request.app.state, limit, cursor, app_id, principal)


@router.post("/api/rag/chunks")
def chunks(request: Request, req: ChunksQueryRequest, principal=Depends(require_jwt)):
    return service.chunks(request.app.state, req, principal)


@router.get("/api/rag/apps/{app_id}/chunks/{chunk_id}/dense-vector")
def dense_vector(request: Request, app_id: str, chunk_id: str, principal=Depends(require_jwt)):
    return service.dense_vector(request.app.state, app_id, chunk_id, principal)


@router.delete("/api/rag/files/{file_id}")
def admin_delete_file(request: Request, file_id: str, app_id: str | None = None, principal=Depends(require_jwt)):
    return service.delete_file(request.app.state, file_id, app_id, principal)


@router.delete("/api/v1/rag/files/{file_id}")
def open_delete_file(request: Request, file_id: str, app_id: str | None = None, principal=Depends(require_principal)):
    return service.client_delete_file(request.app.state, file_id, principal)
