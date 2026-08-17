import logging
import json

import pytest


pytestmark = pytest.mark.unit


def test_log_buffer_keeps_recent_rows_and_assigns_sequence():
    from log_buffer import LogRingBuffer

    buffer = LogRingBuffer(maxlen=2)
    buffer.append({"message": "first"})
    buffer.append({"message": "second"})
    buffer.append({"message": "third"})

    rows = buffer.recent()

    assert [row["message"] for row in rows] == ["second", "third"]
    assert [row["seq"] for row in rows] == [2, 3]


def test_buffer_log_handler_stores_json_log_records():
    from log_buffer import BufferLogHandler, LogRingBuffer
    from logging_config import JsonFormatter

    buffer = LogRingBuffer(maxlen=10)
    handler = BufferLogHandler(buffer)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.buffer.logger")
    old_handlers = logger.handlers
    old_propagate = logger.propagate
    old_level = logger.level
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        logger.info("uploaded", extra={"event": "upload", "file_id": "abc123"})
    finally:
        logger.handlers = old_handlers
        logger.propagate = old_propagate
        logger.setLevel(old_level)

    row = buffer.recent()[0]
    assert row["logger"] == "test.buffer.logger"
    assert row["message"] == "uploaded"
    assert row["event"] == "upload"
    assert row["file_id"] == "abc123"


def test_initial_log_events_are_sse_encoded():
    import main
    from log_buffer import LOG_BUFFER, clear_log_buffer

    clear_log_buffer()
    LOG_BUFFER.append({"message": "log page check", "event": "log_page_check"})

    events, last_seq = main._initial_log_events()
    payload = json.loads(events[0].removeprefix("data: ").strip())

    assert last_seq == 1
    assert payload["seq"] == 1
    assert payload["message"] == "log page check"
    assert payload["event"] == "log_page_check"
