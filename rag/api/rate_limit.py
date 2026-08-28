from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from rag.api.runtime import runtime

_WINDOW_SECONDS = {
    "second": 1,
    "seconds": 1,
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
}

_lock = threading.Lock()
_requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _get_key(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _parse_limit(value: str) -> tuple[int, int]:
    count, window = value.split("/", 1)
    return int(count), _WINDOW_SECONDS[window.strip().lower()]


def _check(request: Request, limit: str, scope: str) -> None:
    max_count, window_seconds = _parse_limit(limit)
    now = time.monotonic()
    bucket_key = (scope, _get_key(request))
    with _lock:
        bucket = _requests[bucket_key]
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()
        if len(bucket) >= max_count:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        bucket.append(now)


def require_rate_limit(request: Request) -> None:
    _check(request, runtime.application.config.api.rate_limit, "open")


def require_index_rate_limit(request: Request) -> None:
    _check(request, runtime.application.config.api.rate_limit_index, "open_index")


def reset_rate_limit() -> None:
    with _lock:
        _requests.clear()
