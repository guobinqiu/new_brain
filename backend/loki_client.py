from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

import httpx


LOKI_TIMEOUT_SECONDS = 5.0


async def query_range(
    query: str,
    start: str,
    end: str,
    limit: int,
    direction: Literal["forward", "backward"],
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=LOKI_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{_base_url()}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": start,
                "end": end,
                "limit": limit,
                "direction": direction,
            },
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("result", [])


async def label_values(label: str) -> list[str]:
    async with httpx.AsyncClient(timeout=LOKI_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{_base_url()}/loki/api/v1/label/{label}/values")
        response.raise_for_status()
        return response.json().get("data", [])


def log_query(node_id: str | None = None, container: str | None = None) -> str:
    labels = []
    if node_id:
        labels.append(f'node_id="{_escape_label(node_id)}"')
    if container:
        labels.append(f'container="{_escape_label(container)}"')
    return "{" + ",".join(labels) + "}"


def trace_query(container: str = "rag-backend") -> str:
    return f'{log_query(container=container)} |= "search_trace"'


def parse_logs(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for stream in streams:
        for ts, line in stream.get("values") or []:
            rows.append({
                "ts": ts,
                "time": _format_timestamp(ts),
                "line": line,
                "parsed": _parse_json(line),
            })
    return sorted(rows, key=lambda row: int(row["ts"]))


def parse_traces(streams: list[dict[str, Any]], app_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = []
    for stream in streams:
        for ts, line in stream.get("values") or []:
            parsed = _parse_json(line)
            if not parsed or parsed.get("event") != "search_trace":
                continue
            if app_id and parsed.get("app_id") != app_id:
                continue
            rows.append({
                **parsed,
                "ts": ts,
                "created_at": parsed.get("time") or _format_timestamp(ts),
                "name": parsed.get("trace_name") or parsed.get("name"),
            })
    return sorted(rows, key=lambda row: int(row["ts"]), reverse=True)[:limit]


def ns_from_ms(value: int) -> str:
    return str(value * 1_000_000)


def _base_url() -> str:
    return os.getenv("LOKI_URL", "http://localhost:3100").rstrip("/")


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _parse_json(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _format_timestamp(ts: str) -> str:
    return datetime.fromtimestamp(int(ts) / 1_000_000_000, timezone.utc).astimezone().isoformat(timespec="seconds")
