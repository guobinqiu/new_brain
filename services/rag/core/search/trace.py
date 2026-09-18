from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Iterator

from shared.tracing import ensure_traceparent, trace_id_from_traceparent


class SearchTrace:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.trace_id = trace_id_from_traceparent(ensure_traceparent()) or "-"
        self._started_at = time.perf_counter()
        self._stages: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._logger = logging.getLogger("services.rag.trace")
        self.result: dict[str, Any] | None = None

    @contextmanager
    def stage(self, name: str, **fields: Any) -> Iterator[dict[str, Any]]:
        if not self.enabled:
            yield fields
            return
        started_at = time.perf_counter()
        stage = {"name": name, **fields}
        try:
            yield stage
        finally:
            stage["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 1)
            with self._lock:
                self._stages.append(stage)

    def finish(self, plan, result_count: int, status: str = "ok", error: str | None = None) -> None:
        extra = {
            "event": "search_trace",
            "trace_id": self.trace_id,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "name": "search",
            "query": plan.query,
            "app_id": plan.app_id,
            "mode": plan.mode,
            "top_k": plan.top_k,
            "file_ids": list(plan.file_ids or []),
            "elapsed_ms": round((time.perf_counter() - self._started_at) * 1000, 1),
            "result_count": result_count,
            "status": status,
            "stages": list(self._stages),
        }
        if error:
            extra["error"] = error
        self.result = {key: value for key, value in extra.items() if key != "event"}
        if self.enabled:
            log_extra = dict(extra)
            log_extra["trace_name"] = log_extra.pop("name")
            self._logger.info("search trace", extra=log_extra)
