from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from rag.auth import validate_app_id


_current_app_id: ContextVar[str | None] = ContextVar("current_app_id", default=None)


def collection_name_for_app(app_id: str) -> str:
    return f"{validate_app_id(app_id)}_chunks"


def current_collection() -> str:
    app_id = _current_app_id.get()
    if app_id is None:
        raise RuntimeError("app collection context is required")
    return collection_name_for_app(app_id)


@contextmanager
def app_collection(app_id: str):
    validate_app_id(app_id)
    token = _current_app_id.set(app_id)
    try:
        yield
    finally:
        _current_app_id.reset(token)
