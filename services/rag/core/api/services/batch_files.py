import asyncio

import httpx
from fastapi import HTTPException

from shared.deadline import request_timeout
from shared.tracing import trace_headers
from services.rag.core.api.schemas import BatchIndexRequest
from services.rag.core.api.services.common import database_principal
from services.rag.core.auth import Principal


async def index_file(state, req: BatchIndexRequest, principal: Principal, authorization: str):
    database_principal(principal, None)
    batch_config = state.config.api.batch_index
    max_files = batch_config.max_files
    if len(req.files) > max_files:
        raise HTTPException(422, f"files exceeds max limit: {max_files}")
    max_concurrency = min(req.max_concurrency or batch_config.max_concurrency, batch_config.max_concurrency)
    max_concurrency = max(1, max_concurrency)
    headers = trace_headers()
    headers["Authorization"] = authorization
    timeout = request_timeout(state.config.api.index_timeout)
    base_url = batch_config.base_url.rstrip("/")
    semaphore = asyncio.Semaphore(max_concurrency)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        files = await asyncio.gather(*[
            _index_file(client, base_url, item, headers, semaphore)
            for item in req.files
        ])
    return {
        "success": all(item.get("success") for item in files),
        "files": files,
    }


async def _index_file(client: httpx.AsyncClient, base_url: str, item, headers: dict[str, str], semaphore: asyncio.Semaphore) -> dict:
    payload = {
        "file_id": item.file_id,
        "s3_url": item.s3_url,
    }
    if item.presigned_url is not None:
        payload["presigned_url"] = item.presigned_url
    if item.filename is not None:
        payload["filename"] = item.filename
    async with semaphore:
        response = await client.post(
            f"{base_url}/api/v1/rag/files",
            headers=headers,
            json=payload,
        )
    return response.json()
