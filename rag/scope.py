from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

from rag.auth import validate_app_id


_current_app_id: ContextVar[str | None] = ContextVar("current_app_id", default=None)


def collection_name_for_app(app_id: str) -> str:
    collection_name = f"{validate_app_id(app_id)}_chunks"
    prefix = os.getenv("RAG_COLLECTION_PREFIX", "").strip("_")
    if not prefix:
        return collection_name
    return f"{prefix}_{collection_name}"


def current_collection() -> str:
    app_id = _current_app_id.get()
    if app_id is None:
        raise RuntimeError("app collection context is required")
    return collection_name_for_app(app_id)


def current_app_id() -> str:
    app_id = _current_app_id.get()
    if app_id is None:
        raise RuntimeError("app collection context is required")
    return app_id


@contextmanager
def app_collection(app_id: str):
    validate_app_id(app_id)
    token = _current_app_id.set(app_id)
    try:
        yield
    finally:
        _current_app_id.reset(token)
