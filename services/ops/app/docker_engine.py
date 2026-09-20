from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx


class DockerEngineClient:
    def __init__(self, socket_path: str = "/var/run/docker.sock"):
        self._socket_path = socket_path
        self._client = httpx.Client(base_url="http://docker", transport=httpx.HTTPTransport(uds=socket_path), timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def list_services(self) -> list[dict]:
        return self._request("GET", "/services").json()

    def inspect_service(self, name: str) -> dict:
        return self._request("GET", f"/services/{quote(name, safe='')}").json()

    def update_service(self, service_id: str, version: int, spec: dict) -> dict:
        return self._request("POST", f"/services/{quote(service_id, safe='')}/update", params={"version": version}, json=spec).json()

    def list_tasks(self, service_name: str) -> list[dict]:
        filters = json.dumps({"service": {service_name: True}}, separators=(",", ":"))
        return self._request("GET", "/tasks", params={"filters": filters}).json()

    def service_logs(self, service_name: str, tail: int = 50) -> str:
        response = self._request("GET", f"/services/{quote(service_name, safe='')}/logs", params={
            "stdout": "1",
            "stderr": "1",
            "timestamps": "1",
            "tail": str(tail),
        })
        return _decode_log_stream(response.content)

    async def stream_service_logs(self, service_name: str, tail: int = 50) -> AsyncIterator[str]:
        transport = httpx.AsyncHTTPTransport(uds=self._socket_path)
        decoder = DockerLogStreamDecoder()
        async with httpx.AsyncClient(base_url="http://docker", transport=transport, timeout=None) as client:
            async with client.stream("GET", f"/services/{quote(service_name, safe='')}/logs", params={
                "stdout": "1",
                "stderr": "1",
                "timestamps": "1",
                "tail": str(tail),
                "follow": "1",
            }) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    for text in decoder.feed(chunk):
                        yield text
                for text in decoder.flush():
                    yield text

    def list_nodes(self) -> list[dict]:
        return self._request("GET", "/nodes").json()

    def inspect_swarm(self) -> dict:
        return self._request("GET", "/swarm").json()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response


def _decode_log_stream(content: bytes) -> str:
    decoder = DockerLogStreamDecoder()
    return "".join(decoder.feed(content) + decoder.flush())


class DockerLogStreamDecoder:
    def __init__(self):
        self._buffer = bytearray()
        self._multiplexed: bool | None = None

    def feed(self, content: bytes) -> list[str]:
        if content:
            self._buffer.extend(content)
        if self._multiplexed is None:
            if len(self._buffer) < 8:
                return []
            self._multiplexed = self._is_header(self._buffer)
        if not self._multiplexed:
            text = bytes(self._buffer).decode("utf-8", errors="replace")
            self._buffer.clear()
            return [text] if text else []

        chunks = []
        while len(self._buffer) >= 8:
            if not self._is_header(self._buffer):
                text = bytes(self._buffer).decode("utf-8", errors="replace")
                self._buffer.clear()
                return chunks + ([text] if text else [])
            size = int.from_bytes(self._buffer[4:8], "big")
            if len(self._buffer) < 8 + size:
                break
            payload = bytes(self._buffer[8:8 + size])
            del self._buffer[:8 + size]
            if payload:
                chunks.append(payload.decode("utf-8", errors="replace"))
        return chunks

    def flush(self) -> list[str]:
        if not self._buffer:
            return []
        text = bytes(self._buffer).decode("utf-8", errors="replace")
        self._buffer.clear()
        return [text]

    @staticmethod
    def _is_header(content: bytes | bytearray) -> bool:
        return content[0] in {1, 2} and content[1:4] == b"\0\0\0"
