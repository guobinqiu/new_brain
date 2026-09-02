from fastapi import APIRouter, Depends, File, Form, UploadFile

from rag.api.rate_limit import require_index_rate_limit, require_rate_limit
from rag.api.services.auth import require_jwt, require_principal
from rag.api.schemas import ChunksQueryRequest, ObjectIndexRequest, PresignRequest
from rag.api.services import files as service


router = APIRouter()


@router.post("/api/open/rag/upload")
async def upload_file(
    file: UploadFile = File(...),
    app_id: str = Form(...),
    principal=Depends(require_jwt),
):
    return await service.upload_file(file, app_id, principal)


@router.post("/api/open/rag/files", dependencies=[Depends(require_index_rate_limit)])
def index_object(req: ObjectIndexRequest, principal=Depends(require_principal)):
    return service.index_object(req, principal)


@router.post("/api/open/rag/files/jobs", status_code=202)
def create_index_job(req: ObjectIndexRequest, principal=Depends(require_principal)):
    return service.create_index_job(req, principal)


@router.post("/api/open/rag/presign")
def presign_object(req: PresignRequest, principal=Depends(require_jwt)):
    return service.presign_object(req, principal)


@router.get("/api/open/rag/files")
def files(limit: int = 50, cursor: str | None = None, app_id: str | None = None, principal=Depends(require_jwt)):
    return service.files(limit, cursor, app_id, principal)


@router.post("/api/open/rag/chunks")
def chunks(req: ChunksQueryRequest, principal=Depends(require_jwt)):
    return service.chunks(req, principal)


@router.post("/api/open/rag/sparse/chunks")
def sparse_chunks(req: ChunksQueryRequest, principal=Depends(require_jwt)):
    return service.sparse_chunks(req, principal)


@router.get("/api/open/rag/apps/{app_id}/chunks/{chunk_id}/dense-vector")
def dense_vector(app_id: str, chunk_id: str, principal=Depends(require_jwt)):
    return service.dense_vector(app_id, chunk_id, principal)


@router.get("/api/open/rag/apps/{app_id}/chunks/{chunk_id}/sparse-vector")
def sparse_vector(app_id: str, chunk_id: str, principal=Depends(require_jwt)):
    return service.sparse_vector(app_id, chunk_id, principal)


@router.delete("/api/open/rag/files/{file_id}", dependencies=[Depends(require_rate_limit)])
def delete_file(file_id: str, app_id: str | None = None, principal=Depends(require_principal)):
    return service.delete_file(file_id, app_id, principal)
