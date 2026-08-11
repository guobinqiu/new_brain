from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")

STARTUP_RETRY_COUNT = 30
STARTUP_RETRY_DELAY_SECONDS = 1


def run_with_startup_retry(operation: Callable[[], T]) -> T:
    last_error: Exception | None = None
    for attempt in range(STARTUP_RETRY_COUNT):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt == STARTUP_RETRY_COUNT - 1:
                break
            time.sleep(STARTUP_RETRY_DELAY_SECONDS)
    raise last_error
