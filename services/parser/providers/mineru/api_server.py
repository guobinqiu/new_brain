from __future__ import annotations

import hashlib
import mimetypes
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.parse import urlsplit

import httpx

from services.parser.common.schema import Block
from services.parser.providers.mineru.normalizer import content_list_to_blocks
from shared.config import MineruParserConfig
from shared.retry import retry_call
from shared.upstream import UpstreamServiceError, upstream_error


POLL_INTERVAL_SECONDS = 3.0


class MineruApiServerClient:
    def __init__(self, config: MineruParserConfig, *, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client

    def start(self) -> None:
        if self._client is None:
            self._client = httpx.Client(timeout=self.config.timeout)

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def parse_file(self, filepath: str, *, original_filename: str) -> list[Block]:
        return retry_call(
            lambda: self._parse_file_once(filepath, original_filename=original_filename),
            self.config.retry,
            operation_name="parser.mineru.parse_file",
        )

    def _parse_file_once(self, filepath: str, *, original_filename: str) -> list[Block]:
        if not self.config.base_url:
            raise ValueError("mineru.base_url is required")
        if self._client is None:
            self.start()
        path = Path(filepath)
        try:
            file_id = self._upload_file(path, original_filename)
            job = self._create_job(file_id)
            job = self._poll_job(job)
            content_file_id = self._structured_content_file_id(job)
            response = self._client.get(self._url(f"/v1/files/{content_file_id}/content"), headers=self._api_headers(), timeout=self.config.timeout)
            response.raise_for_status()
            blocks = content_list_to_blocks(response.json())
        except UpstreamServiceError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            response = exc.response if isinstance(exc, httpx.HTTPStatusError) else None
            retryable = response is not None and 500 <= response.status_code < 600
            raise upstream_error("parser", exc, retryable=retryable) from exc
        if not blocks:
            raise ValueError(f"MinerU api-server returned empty parse result: {original_filename}")
        return blocks

    def _upload_file(self, path: Path, filename: str) -> str:
        body = {
            "filename": filename,
            "bytes": path.stat().st_size,
            "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "purpose": "parse",
            "sha256sum": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        response = self._client.post(self._url("/v1/uploads"), headers=self._api_headers(), json=body, timeout=self.config.timeout)
        response.raise_for_status()
        data = response.json()
        status = data["status"]
        if status == "pending":
            upload_url = urljoin(self.config.base_url.rstrip("/") + "/", data["upload_url"])
            headers = data.get("upload_headers") if isinstance(data.get("upload_headers"), dict) else {}
            if _same_origin(self.config.base_url, upload_url):
                headers = {**headers, **self._api_headers()}
            upload_response = self._client.request(data.get("upload_method") or "PUT", upload_url, headers=headers, content=path.read_bytes(), timeout=self.config.timeout)
            upload_response.raise_for_status()
            complete_response = self._client.post(self._url(f"/v1/uploads/{data['id']}/complete"), headers=self._api_headers(), timeout=self.config.timeout)
            complete_response.raise_for_status()
            data = complete_response.json()
        elif status != "completed":
            raise UpstreamServiceError(service="parser", error=f"MinerU upload status is {status}", retryable=False, status_code=502)
        return data["file"]["id"]

    def _create_job(self, file_id: str) -> dict:
        response = self._client.post(
            self._url("/v1/parse/jobs"),
            headers=self._api_headers(),
            json={
                "files": [{"source": {"type": "file_id", "file_id": file_id}}],
                "tier": self.config.tier,
                "output_formats": ["structured_content"],
            },
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _poll_job(self, job: dict) -> dict:
        job_id = job["job_id"]
        deadline = time.monotonic() + self.config.timeout
        while True:
            status = job["status"]
            if status == "completed":
                return job
            if status in {"failed", "partial", "canceled"}:
                raise UpstreamServiceError(service="parser", error=_job_error(job), retryable=False, status_code=502)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UpstreamServiceError(service="parser", error=f"MinerU job {job_id} polling timed out", retryable=True, status_code=504)
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UpstreamServiceError(service="parser", error=f"MinerU job {job_id} polling timed out", retryable=True, status_code=504)
            response = self._client.get(self._url(f"/v1/parse/jobs/{job_id}"), headers=self._api_headers(), timeout=min(self.config.timeout, remaining))
            response.raise_for_status()
            job = response.json()

    def _structured_content_file_id(self, job: dict) -> str:
        for file_result in job.get("files") or []:
            if file_result.get("status") != "completed":
                continue
            output_files = file_result.get("output_files")
            if not isinstance(output_files, dict):
                continue
            structured = output_files.get("structured_content")
            if isinstance(structured, dict) and structured.get("file_id"):
                return structured["file_id"]
        raise UpstreamServiceError(service="parser", error="MinerU job completed without structured_content output", retryable=False, status_code=502)

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}{path}"

    def _api_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}


def _job_error(job: dict) -> str:
    for file_result in job.get("files") or []:
        error = file_result.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return f"MinerU job status is {job.get('status')}"


def _same_origin(base_url: str, target_url: str) -> bool:
    base = urlsplit(base_url)
    target = urlsplit(target_url)
    base_port = base.port or (443 if base.scheme == "https" else 80)
    target_port = target.port or (443 if target.scheme == "https" else 80)
    return (base.scheme, base.hostname, base_port) == (target.scheme, target.hostname, target_port)
