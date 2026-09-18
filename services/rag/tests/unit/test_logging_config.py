import json
import logging
from io import StringIO

import pytest


pytestmark = pytest.mark.unit


def test_json_formatter_outputs_one_json_object_per_line():
    from shared.logging_config import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.json.formatter")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info("application started", extra={"event": "startup", "component": "api"})

    row = json.loads(stream.getvalue())
    assert row["level"] == "INFO"
    assert row["logger"] == "test.json.formatter"
    assert row["event"] == "startup"
    assert row["message"] == "application started"
    assert row["component"] == "api"
    assert "time" in row


def test_configure_logging_writes_stdout_and_optional_file(tmp_path):
    from shared.logging_config import configure_logging
    from shared.config import LoggingConfig

    stream = StringIO()
    log_file = tmp_path / "rag.jsonl"

    configure_logging(
        LoggingConfig(level="INFO", file=str(log_file), max_bytes=1024, backup_count=2, search_trace=True),
        stream=stream,
    )

    logging.getLogger("services.rag").info("uploaded", extra={"event": "upload", "document_filename": "a.pdf"})

    stdout_row = json.loads(stream.getvalue())
    file_row = json.loads(log_file.read_text(encoding="utf-8"))
    assert stdout_row["event"] == "upload"
    assert file_row["document_filename"] == "a.pdf"


def test_configure_logging_resolves_relative_file_from_project_root(monkeypatch, tmp_path):
    import shared.logging_config as logging_config
    from shared.logging_config import configure_logging
    from shared.config import LoggingConfig

    stream = StringIO()
    monkeypatch.setattr(logging_config, "PROJECT_ROOT", tmp_path)

    configure_logging(
        LoggingConfig(level="INFO", file="logs/rag.log", max_bytes=1024, backup_count=2, search_trace=True),
        stream=stream,
    )

    logging.getLogger("services.rag").info("startup", extra={"event": "startup"})

    assert json.loads((tmp_path / "logs" / "rag.log").read_text(encoding="utf-8"))["event"] == "startup"


def test_configure_logging_without_file_only_writes_stdout(tmp_path):
    from shared.logging_config import configure_logging
    from shared.config import LoggingConfig

    stream = StringIO()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    configure_logging(LoggingConfig(level="INFO", search_trace=True), stream=stream)

    logging.getLogger("services.rag").info("startup", extra={"event": "startup"})

    assert json.loads(stream.getvalue())["event"] == "startup"
    assert not list(log_dir.iterdir())
