from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Any


class LogRingBuffer:
    def __init__(self, maxlen: int = 500):
        self._rows = deque(maxlen=maxlen)
        self._seq = 0
        self._condition = threading.Condition()

    def append(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            self._seq += 1
            stored = {"seq": self._seq, **row}
            self._rows.append(stored)
            self._condition.notify_all()
            return stored

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._condition:
            rows = list(self._rows)
        if limit is None:
            return rows
        return rows[-limit:]

    def after(self, seq: int) -> list[dict[str, Any]]:
        with self._condition:
            return [row for row in self._rows if row["seq"] > seq]

    def clear(self) -> None:
        with self._condition:
            self._rows.clear()
            self._seq = 0


class BufferLogHandler(logging.Handler):
    def __init__(self, buffer: LogRingBuffer):
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            row = json.loads(self.format(record))
            self.buffer.append(row)
        except Exception:
            self.handleError(record)


LOG_BUFFER = LogRingBuffer()


def recent_logs(limit: int = 200) -> list[dict[str, Any]]:
    return LOG_BUFFER.recent(limit)


def logs_after(seq: int) -> list[dict[str, Any]]:
    return LOG_BUFFER.after(seq)


def clear_log_buffer() -> None:
    LOG_BUFFER.clear()
