import json
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from api.runtime import runtime
from auth import Principal
from collection_names import validate_app_id


def require_ready():
    if not runtime.application.ready:
        raise HTTPException(503, "search is not initialized")


def require_database_ready():
    if not runtime.application.database.ready:
        raise HTTPException(503, "database is not initialized")


def component_config(component: Any) -> dict[str, Any] | None:
    if component is None:
        return None
    data = {
        "name": getattr(component, "name", None),
        "model_name": getattr(component, "model_name", None),
        "model_path": getattr(component, "model_path", None),
        "tokenizer": getattr(component, "tokenizer", None),
        "import_path": getattr(component, "import_path", None),
    }
    return {key: value for key, value in data.items() if value is not None}


def component_status(component: Any, *, enabled: bool, error: str | None = None) -> str:
    if not enabled:
        return "disabled"
    if error:
        return "error"
    if not runtime.application.ready:
        return "loading"
    return "ready" if is_ready(component) else "loading"


def required_component_status(component: Any, *, error: str | None = None) -> str:
    if error:
        return "error"
    if not runtime.application.ready:
        return "loading"
    return "ready" if is_ready(component) else "loading"


def component_model(component_config: Any) -> str | None:
    if component_config is None:
        return None
    return getattr(component_config, "model_name", None) or getattr(component_config, "name", None)


def is_ready(component: Any) -> bool:
    return bool(getattr(component, "ready", False))


def store_context(principal: Principal):
    principal = effective_principal(principal)
    if not principal.app_id:
        return nullcontext()
    context = getattr(runtime.application.store, "app_context", None)
    if callable(context):
        return context(principal.app_id)
    return nullcontext()


def effective_principal(principal) -> Principal:
    if isinstance(principal, Principal):
        return principal
    return Principal(type="admin", app_id="")


def database_principal(principal: Principal, app_id: str | None) -> Principal:
    principal = effective_principal(principal)
    if principal.type == "admin":
        selected_app_id = app_id or principal.app_id
        if not selected_app_id:
            raise HTTPException(status_code=400, detail="app_id is required")
        validate_app_id(selected_app_id)
        return Principal(type="admin", app_id=selected_app_id)
    if app_id and app_id != principal.app_id:
        raise HTTPException(status_code=403, detail="app_id is not allowed")
    return principal


def scoped_store(principal: Principal):
    scoped_methods = {
        "delete_file_chunks",
        "get_search_documents",
        "get_total_chunks",
        "list_chunks",
        "search_dense",
        "search_hybrid",
        "search_sparse",
    }

    class ScopedStore:
        def __getattr__(self, name):
            attr = getattr(runtime.application.store, name)
            if not callable(attr) or name not in scoped_methods:
                return attr

            def call(*args, **kwargs):
                if not app_database_exists(principal):
                    return 0 if name in {"delete_file_chunks", "get_total_chunks"} else []
                with store_context(principal):
                    return attr(*args, **kwargs)

            return call

    return ScopedStore()


def require_app_database(principal: Principal) -> None:
    principal = effective_principal(principal)
    if principal.app_id and not app_database_exists(principal):
        raise HTTPException(status_code=409, detail="app database is not initialized")


def app_database_status(app_id: str) -> dict[str, Any]:
    try:
        validate_app_id(app_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    principal = Principal(type="admin", app_id=app_id)
    exists = app_database_exists(principal)
    chunk_count = scoped_store(principal).get_total_chunks(None) if exists else 0
    return {
        "app_id": app_id,
        "exists": exists,
        "chunk_count": chunk_count,
        "empty": chunk_count == 0,
    }


def app_database_exists(principal: Principal) -> bool:
    principal = effective_principal(principal)
    if not principal.app_id:
        return True
    return runtime.application.store.app_collection_exists(principal.app_id)


def iso_datetime(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().isoformat(timespec="seconds")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sse_data(value: Any) -> str:
    return f"data: {json.dumps(value, ensure_ascii=False)}\n\n"
