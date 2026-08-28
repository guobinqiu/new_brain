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
    if not labels:
        labels.append('container=~".+"')
    return "{" + ",".join(labels) + "}"


def trace_query(container: str | None = None, app_id: str | None = None) -> str:
    query = f'{log_query(container=container)} |= "search_trace"'
    if app_id:
        query += f' | json | app_id="{_escape_label(app_id)}"'
    return query


def parse_logs(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for stream in streams:
        labels = stream.get("stream") or {}
        for ts, line in stream.get("values") or []:
            rows.append({
                "ts": ts,
                "time": _format_timestamp(ts),
                "node_id": labels.get("node_id"),
                "container": labels.get("container"),
                "line": line,
                "parsed": _parse_json(line),
            })
    return sorted(rows, key=lambda row: int(row["ts"]))


def parse_traces(streams: list[dict[str, Any]], app_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
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
    return sorted(rows, key=lambda row: int(row["ts"]))[:limit]


def ns_from_ms(value: int) -> str:
    return str(value * 1_000_000)


def next_ns(value: str) -> str:
    return str(int(value) + 1)


def timestamp_to_ns(value: str | None, default_ms: int) -> str:
    if value is None or str(value).strip() == "":
        return ns_from_ms(default_ms)

    text = str(value).strip()
    if text.isdigit():
        if len(text) >= 16:
            return text
        if len(text) >= 13:
            return ns_from_ms(int(text))
        return ns_from_ms(int(text) * 1000)

    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return str(int(parsed.timestamp() * 1_000_000_000))


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
