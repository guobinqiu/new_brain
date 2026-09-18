from __future__ import annotations

import json
from urllib.parse import quote

import httpx


class DockerEngineClient:
    def __init__(self, socket_path: str = "/var/run/docker.sock"):
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

    def service_logs(self, service_name: str, tail: int = 200) -> str:
        response = self._request("GET", f"/services/{quote(service_name, safe='')}/logs", params={
            "stdout": "1",
            "stderr": "1",
            "timestamps": "1",
            "tail": str(tail),
        })
        return response.text

    def list_nodes(self) -> list[dict]:
        return self._request("GET", "/nodes").json()

    def inspect_swarm(self) -> dict:
        return self._request("GET", "/swarm").json()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response
