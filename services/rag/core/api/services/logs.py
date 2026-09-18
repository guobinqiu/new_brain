from datetime import datetime, timezone

from fastapi import HTTPException

from services.rag.core.loki_client import container_service, label_values, log_query, next_ns, parse_logs, query_range, timestamp_to_ns


async def logs(
    state,
    node_id: str | None = None,
    container: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    _=None,
): 
    if not state.config.logging.loki_url:
        raise HTTPException(503, "log storage is not configured")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ns = timestamp_to_ns(start, now_ms - 15 * 60 * 1000)
    end_ns = timestamp_to_ns(end, now_ms)
    if limit <= 0:
        raise HTTPException(400, "limit must be greater than 0")
    page_limit = limit
    streams = await query_range(
        state.config.logging.loki_url,
        log_query(node_id=node_id, container=container, include_tasks=True),
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


async def log_label_values(state, label: str, _):
    if not state.config.logging.loki_url:
        raise HTTPException(503, "log storage is not configured")
    if label not in {"container", "node_id"}:
        raise HTTPException(400, "unsupported log label")
    values = await label_values(state.config.logging.loki_url, label)
    if label == "container":
        values = sorted({container_service(value) for value in values})
    return {"values": values}
