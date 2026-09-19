from __future__ import annotations

import os
from pathlib import Path

import yaml

from shared.config import AppConfig, parse_app_config
from shared.paths import PROJECT_ROOT
from services.rag.core.auth import validate_app_id


CONFIG_FILE_ENV = "RAG_CONFIG_FILE"
VECTOR_SERVICES = ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud")


def load_app_config() -> AppConfig:
    config_path = os.getenv(CONFIG_FILE_ENV, str(PROJECT_ROOT / "services/rag/config/rag.yaml"))
    return load_config_file(_resolve_config_path(config_path))


def load_config_file(path: str | Path) -> AppConfig:
    config_path = _resolve_config_path(str(path))
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    available_components = _available_components(raw)
    _select_enabled_components(raw)
    _select_enabled_database(raw)
    _apply_environment(raw)
    config = parse_app_config(raw)
    object.__setattr__(config, "name", config_path.stem)
    object.__setattr__(config, "available_components", available_components)
    return config


def _resolve_config_path(value: str) -> Path:
    config_path = Path(value)
    if config_path.is_absolute() or config_path.exists():
        return config_path
    if config_path.parts and config_path.parts[0] in ("rag", "services"):
        return PROJECT_ROOT / config_path
    raise FileNotFoundError(value)


def _apply_environment(raw: dict) -> None:
    services = raw.get("services")
    if isinstance(services, dict):
        service_api_key = os.getenv("SERVICE_API_KEY")
        services["parser"]["api_key"] = os.getenv("PARSER_API_KEY", service_api_key)
        inference = services["inference"]
        inference["api_key"] = os.getenv("INFERENCE_API_KEY", service_api_key)
        vector = services["vector"]
        vector["api_key"] = None
        vector["token"] = None
        for provider, key, secret_env in (
            ("qdrant", "api_key", "QDRANT_API_KEY"),
            ("milvus", "token", "MILVUS_TOKEN"),
            ("qdrant_cloud", "api_key", "QDRANT_CLOUD_API_KEY"),
            ("milvus_cloud", "token", "MILVUS_CLOUD_TOKEN"),
        ):
            if vector.get("provider") == provider:
                vector[key] = os.getenv(secret_env)
                break
    auth = raw.setdefault("auth", {})
    if raw.get("database") is not None:
        password = os.environ["RAG_ADMIN_PASSWORD"]
        if not password:
            raise ValueError("RAG_ADMIN_PASSWORD is required when database is enabled")
        auth["apps"] = []
    else:
        password = os.getenv("RAG_ADMIN_PASSWORD", "")
        auth["apps"] = _load_app_credentials(auth.get("apps", []))
    auth.setdefault("admin", {})["password"] = password
    _apply_database_secret(raw)


def _load_app_credentials(apps: list) -> list[dict[str, str]]:
    if not isinstance(apps, list):
        raise ValueError("auth.apps must be a list of app credentials")
    app_ids = set()
    api_keys = set()
    credentials = []
    for app in apps:
        if not isinstance(app, dict) or not isinstance(app.get("app_id"), str):
            raise ValueError("auth.apps entries require an app_id string")
        app_id = validate_app_id(app["app_id"])
        api_key = app.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("auth.apps entries require a nonempty api_key")
        if app_id in app_ids or api_key in api_keys:
            raise ValueError("auth.apps app_id and api_key must each be unique")
        app_ids.add(app_id)
        api_keys.add(api_key)
        credentials.append({"app_id": app_id, "api_key": api_key})
    return credentials


def _apply_database_secret(raw: dict) -> None:
    database = raw.get("database")
    if not isinstance(database, dict):
        return
    url = os.getenv("DATABASE_URL")
    if url:
        database["url"] = url


def _select_enabled_components(raw: dict) -> None:
    vector_backends = {
        name: raw["vector_db"].get(name)
        for name in VECTOR_SERVICES
        if isinstance(raw["vector_db"].get(name), dict)
    }
    raw["services"] = {
        "parser": dict(raw.get("parser") or {}),
        "inference": dict(raw.get("inference") or {}),
        "vector": _select_one_enabled(vector_backends, "vector backend", provider_from_key=True),
    }


def _select_enabled_database(raw: dict) -> None:
    database = raw.get("db")
    raw["database"] = database
    if _is_component_group(database):
        if any(bool(config.get("enable")) for config in database.values()):
            raw["database"] = _select_one_enabled(database, "database", provider_from_key=True)
        else:
            raw["database"] = None


def _select_one_enabled(section: dict, section_name: str, provider_from_key: bool = False) -> dict:
    enabled = [
        (name, config)
        for name, config in section.items()
        if isinstance(config, dict) and bool(config.get("enable"))
    ]
    if len(enabled) != 1:
        raise ValueError(f"{section_name} must enable exactly one component")
    name, config = enabled[0]
    selected = dict(config)
    if provider_from_key:
        selected.setdefault("provider", name)
    return selected


def _available_components(raw: dict) -> dict[str, list[dict[str, object]]]:
    components = {
        "parser": [{"name": "parser", "model_name": None, "active": True}],
        "inference": [{"name": "inference", "model_name": None, "active": True}],
        "database": _component_options(raw.get("db")),
    }
    vector_backends = {
        name: raw["vector_db"].get(name)
        for name in VECTOR_SERVICES
        if isinstance(raw["vector_db"].get(name), dict)
    }
    components["vector"] = _component_group_options(vector_backends)
    return components


def _component_options(section) -> list[dict[str, object]]:
    if not isinstance(section, dict):
        return []
    if _is_component_group(section):
        return _component_group_options(section)
    return [{
        "name": section.get("name") or section.get("type") or section.get("module"),
        "model_name": section.get("model_name"),
        "active": True,
    }]


def _component_group_options(section) -> list[dict[str, object]]:
    options = []
    for name, config in section.items():
        if not isinstance(config, dict):
            continue
        options.append({
            "name": config.get("name") or config.get("type") or config.get("module") or name,
            "model_name": config.get("model_name"),
            "active": bool(config.get("enable")),
        })
    return options


def _is_component_group(section) -> bool:
    if not isinstance(section, dict):
        return False
    if any(key in section for key in ("name", "type", "module")):
        return False
    return all(isinstance(value, dict) for value in section.values())
