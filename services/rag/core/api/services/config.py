from typing import Any

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from services.rag.core.nodes import node_id


def get_config(state, _):
    return config_payload(state)


def config_payload(state) -> dict[str, Any]:
    search = state.config.search
    cfg = {
        "mode": search.mode,
        "top_k": search.top_k,
        "rerank": search.rerank,
        "rerank_available": getattr(getattr(state, "inference_client", None), "rerank", None) is not None,
        "rerank_fetch_k": search.rerank_fetch_k,
        "hybrid": {
            "rrf_k": search.rrf_k,
        },
    }
    cfg["node_id"] = node_id()
    cfg["config_name"] = state.config_name
    cfg["capabilities"] = capabilities(state)
    cfg["services"] = services_config(state)
    cfg["available_components"] = state.config.available_components
    return cfg


def capabilities(state) -> dict[str, bool]:
    vector = state.vector_client
    return {
        "dense_vector": _supports(vector, "supports_dense_vector"),
        "sparse_vector": _supports(vector, "supports_sparse_vector"),
        "app_management": state.config.database is not None,
        "file_records": state.config.database is not None,
        "file_upload": bool(state.config.storage.endpoint_url),
    }


def _supports(component: Any, method_name: str, *args) -> bool:
    method = getattr(component, method_name, None)
    if not callable(method):
        return False
    return bool(method(*args))


def services_config(state) -> dict[str, dict[str, Any]]:
    services = state.config.services
    result = {
        "parser": _service_config(services.parser),
        "inference": _service_config(services.inference),
        "vector": _service_config(services.vector),
    }
    if state.config.database is not None:
        result["database"] = _database_config(state.config.database)
    return result


def _service_config(service: Any) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "base_url": service.base_url,
            "timeout": service.timeout,
        }.items()
        if value is not None
    }


def _database_config(database: Any) -> dict[str, Any]:
    connection = conninfo_to_dict(database.url)
    for key in ("password", "sslpassword", "passfile", "sslkey", "oauth_client_secret"):
        if key in connection:
            connection[key] = "***"
    return {
        key: value
        for key, value in {
            "provider": database.provider,
            "url": make_conninfo(**connection),
            "pool_size": database.pool_size,
        }.items()
        if value is not None
    }


def profile(state) -> dict[str, Any]:
    return {
        "config_name": state.config_name,
        "services": services_config(state),
    }
