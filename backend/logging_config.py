from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from schema import LoggingConfig


RESERVED_ATTRS = set(logging.makeLogRecord({}).__dict__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        row = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            row["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in RESERVED_ATTRS and not key.startswith("_"):
                row[key] = value
        return json.dumps(row, ensure_ascii=False, default=str)


def configure_logging(config: LoggingConfig, stream: TextIO | None = None) -> None:
    formatter = JsonFormatter()
    handlers: list[logging.Handler] = []

    stdout_handler = logging.StreamHandler(stream or sys.stdout)
    stdout_handler.setFormatter(formatter)
    handlers.append(stdout_handler)

    if config.file:
        path = _log_file_path(config.file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root = logging.getLogger()
    for handler in root.handlers:
        handler.close()
    root.handlers = handlers
    root.setLevel(_level(config.level))

    for logger_name in ("rag.app", "rag.trace", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(_level(config.level))


def _log_file_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _level(value: str) -> int:
    level = logging.getLevelName(value.upper())
    if isinstance(level, int):
        return level
    raise ValueError(f"unsupported logging.level: {value}")
