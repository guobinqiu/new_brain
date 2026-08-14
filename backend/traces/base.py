from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TraceRecord:
    id: str
    created_at: str
    query: str
    mode: str
    sparse_mode: str
    rerank: bool
    top_k: int
    result_count: int
    total_ms: float
    stage_durations: dict[str, float]
    stage_details: list[dict]


@dataclass(frozen=True)
class TracePage:
    traces: list[TraceRecord]
    next_cursor: str | None
    has_more: bool


class TraceRepository(Protocol):
    ready: bool

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def append(self, trace: dict) -> None: ...
    def list_traces(self, limit: int = 50, cursor: str | None = None) -> TracePage: ...
    def cleanup_before_days(self, days: int = 30) -> int: ...
