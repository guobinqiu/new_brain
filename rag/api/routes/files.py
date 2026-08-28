from fastapi import APIRouter, Depends, File, Form, UploadFile

from rag.api.rate_limit import require_index_rate_limit, require_rate_limit
from rag.api.services.auth import require_aksk, require_jwt
from rag.api.schemas import AdminIndexJobRequest, ChunksQueryRequest, ObjectIndexRequest, PresignRequest
from rag.api.services import files as service


router = APIRouter()


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    app_id: str = Form(...),
    principal=Depends(require_jwt),
):
    return await service.upload_file(file, app_id, principal)


@router.post("/api/open/files", dependencies=[Depends(require_index_rate_limit)])
def client_index_object(req: ObjectIndexRequest, principal=Depends(require_aksk)):
    return service.client_index_object(req, principal)


@router.post("/api/files")
def index_object(req: ObjectIndexRequest, principal=Depends(require_jwt)):
    return service.index_object(req, principal)


@router.post("/api/open/files/jobs", status_code=202)
def client_create_index_job(req: ObjectIndexRequest, principal=Depends(require_aksk)):
    return service.client_create_index_job(req, principal)


@router.post("/api/files/jobs", status_code=202)
def create_index_job(req: AdminIndexJobRequest, principal=Depends(require_jwt)):
    return service.create_index_job(req, principal)


@router.post("/api/presign")
def presign_object(req: PresignRequest, principal=Depends(require_jwt)):
    return service.presign_object(req, principal)


@router.get("/api/files")
def files(limit: int = 50, cursor: str | None = None, app_id: str | None = None, principal=Depends(require_jwt)):
    return service.files(limit, cursor, app_id, principal)


@router.post("/api/chunks")
def chunks(req: ChunksQueryRequest, principal=Depends(require_jwt)):
    return service.chunks(req, principal)


@router.delete("/api/open/files/{file_id}", dependencies=[Depends(require_rate_limit)])
def client_delete_file(file_id: str, principal=Depends(require_aksk)):
    return service.client_delete_file(file_id, principal)


@router.delete("/api/files/{file_id}")
def delete_file(file_id: str, app_id: str | None = None, principal=Depends(require_jwt)):
    return service.delete_file(file_id, app_id, principal)
