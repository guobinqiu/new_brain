from datetime import datetime, timezone

from fastapi import HTTPException

from rag.loki_client import label_values, log_query, next_ns, parse_logs, query_range, timestamp_to_ns


async def logs(
    node_id: str | None = None,
    container: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    _=None,
):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ns = timestamp_to_ns(start, now_ms - 15 * 60 * 1000)
    end_ns = timestamp_to_ns(end, now_ms)
    if limit <= 0:
        raise HTTPException(400, "limit must be greater than 0")
    page_limit = limit
    streams = await query_range(
        log_query(node_id=node_id, container=container),
        start_ns,
        end_ns,
        page_limit,
        "forward",
    )
    rows = parse_logs(streams)
    return {
        "logs": rows,
        "has_more": len(rows) >= page_limit,
        "next_start": next_ns(rows[-1]["ts"]) if rows else None,
    }


async def log_label_values(label: str, _):
    if label not in {"container", "node_id"}:
        raise HTTPException(400, "unsupported log label")
    return {"values": await label_values(label)}
