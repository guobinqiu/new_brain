from __future__ import annotations

from pathlib import Path

import httpx

from shared.service_auth import service_auth_headers
from shared.tracing import trace_headers
from shared.deadline import request_timeout
from shared.upstream import internal_error
from services.rag.clients.parser.base import ParserClient


class HttpParserClient(ParserClient):
    ready = True

    def __init__(self, base_url: str, timeout: float = 300.0, api_key: str | None = None, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)

    def start(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.ready = False
        self._client.close()

    def stop(self) -> None:
        self.close()

    def ping(self) -> bool:
        try:
            response = self._client.get(
                f"{self.base_url}/ready",
                headers={**service_auth_headers(self.api_key), **trace_headers()},
                timeout=min(self.timeout, 1.0),
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[dict]:
        try:
            filename = original_filename or Path(filepath).name
            with open(filepath, "rb") as file:
                response = self._client.post(
                    f"{self.base_url}/v1/parse/file",
                    files={"file": (filename, file, "application/octet-stream")},
                    headers={**service_auth_headers(self.api_key), **trace_headers()},
                    timeout=request_timeout(self.timeout),
                )
            response.raise_for_status()
            return response.json()["blocks"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise internal_error("parser", exc) from exc
