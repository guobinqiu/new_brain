from datetime import datetime, timezone

from fastapi import HTTPException

from rag.loki_client import next_ns, parse_traces, query_range, timestamp_to_ns, trace_query


async def traces(
    app_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    _=None,
):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if limit <= 0:
        raise HTTPException(400, "limit must be greater than 0")
    page_limit = limit
    streams = await query_range(
        trace_query(app_id=app_id),
        timestamp_to_ns(start, now_ms - 24 * 60 * 60 * 1000),
        timestamp_to_ns(end, now_ms),
        page_limit,
        "forward",
    )
    rows = parse_traces(streams, app_id=app_id, limit=page_limit)
    return {
        "traces": rows,
        "has_more": len(rows) >= page_limit,
        "next_start": next_ns(rows[-1]["ts"]) if rows else None,
    }
