from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


PEER_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class NodeResult:
    node_id: str
    base_url: str
    status: str
    latency_ms: float | None
    data: dict | None
    error: str | None


def node_id() -> str:
    return os.getenv("RAG_NODE_ID", "node-1")


def parse_peers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def local_result(data: dict) -> NodeResult:
    return NodeResult(
        node_id=node_id(),
        base_url="local",
        status="ok",
        latency_ms=0.0,
        data=data,
        error=None,
    )


async def fetch_peers(
    peers: list[str],
    path: str,
    authorization: str | None,
    client: httpx.AsyncClient | None = None,
) -> list[NodeResult]:
    headers = {"Authorization": authorization} if authorization else {}
    if client is not None:
        return await asyncio.gather(*[_fetch_peer(client, peer, path, headers) for peer in peers])
    async with httpx.AsyncClient(timeout=PEER_TIMEOUT_SECONDS) as owned_client:
        return await asyncio.gather(*[_fetch_peer(owned_client, peer, path, headers) for peer in peers])


async def _fetch_peer(client, base_url: str, path: str, headers: dict[str, str]) -> NodeResult:
    started = time.perf_counter()
    url = f"{base_url.rstrip('/')}{path}"
    fallback_id = _fallback_node_id(base_url)
    try:
        response = await client.get(url, headers=headers)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code != 200:
            return NodeResult(fallback_id, base_url, "unreachable", None, None, f"status {response.status_code}")
        data = response.json()
        return NodeResult(str(data.get("node_id") or fallback_id), base_url, "ok", latency_ms, data, None)
    except Exception as exc:
        return NodeResult(fallback_id, base_url, "unreachable", None, None, str(exc))


def _fallback_node_id(base_url: str) -> str:
    parsed = urlparse(base_url)
    return parsed.hostname or parsed.path
