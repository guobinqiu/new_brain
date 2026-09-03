from pathlib import Path

from rag.api.runtime import runtime


def upload_file(api_client, app_id: str, path: str | Path, *, filename: str | None = None, content_type: str = "text/plain") -> dict:
    file_path = Path(path)
    upload_name = filename or file_path.name
    with file_path.open("rb") as handle:
        response = api_client.post(
            "/api/open/rag/upload",
            data={"app_id": app_id},
            files={"file": (upload_name, handle, content_type)},
        )
    assert response.status_code == 200, response.text
    return response.json()


def presign_file(api_client, s3_url: str) -> str:
    response = api_client.post("/api/open/rag/presign", json={"s3_url": s3_url})
    assert response.status_code == 200, response.text
    return response.json()["presigned_url"]


def index_uploaded_file(
    app_api_client,
    api_client,
    path: str | Path,
    *,
    filename: str | None = None,
    content_type: str = "text/plain",
    file_id: str | None = None,
) -> str:
    uploaded = upload_file(api_client, app_api_client.app_id, path, filename=filename, content_type=content_type)
    presigned_url = presign_file(api_client, uploaded["s3_url"])
    indexed_file_id = file_id or uploaded["file_id"]
    response = app_api_client.post(
        "/api/open/rag/files",
        json={
            "file_id": indexed_file_id,
            "presigned_url": presigned_url,
            "s3_url": uploaded["s3_url"],
            "filename": uploaded["filename"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"file_id": indexed_file_id}
    return indexed_file_id


def indexed_file_record(app_api_client, file_id: str) -> dict:
    with runtime.application.store.app_context(app_api_client.app_id):
        documents = runtime.application.store.get_search_documents(runtime.application.store.build_file_filter([file_id]))
    document = next((item for item in documents if (item.get("metadata") or {}).get("file_id") == file_id), None)
    assert document is not None
    return document.get("metadata") or {}
