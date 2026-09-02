from __future__ import annotations

import os
from pathlib import Path

import yaml

from rag.schema import AppConfig, parse_app_config


CONFIG_DIR = Path(__file__).resolve().parent / "config"
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
MODELS_DIR = PROJECT_ROOT / "models"
CONFIG_FILE_ENV = "CONFIG_FILE"


def load_app_config() -> AppConfig:
    config_path = os.getenv(CONFIG_FILE_ENV)
    if not config_path:
        raise RuntimeError(f"{CONFIG_FILE_ENV} is required")
    return load_config_file(_resolve_config_path(config_path))


def load_config_file(path: str | Path) -> AppConfig:
    config_path = _resolve_config_path(str(path))
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    available_components = _available_components(raw)
    _select_enabled_components(raw)
    _resolve_model_paths(raw)
    _apply_runtime_overrides(raw)
    config = parse_app_config(raw)
    object.__setattr__(config, "name", config_path.stem)
    object.__setattr__(config, "available_components", available_components)
    return config


def _resolve_config_path(value: str) -> Path:
    config_path = Path(value)
    if config_path.is_absolute() or config_path.exists():
        return config_path
    if config_path.parts and config_path.parts[0] == "rag":
        return PROJECT_ROOT / config_path
    raise FileNotFoundError(value)


def _apply_runtime_overrides(raw: dict) -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url and isinstance(raw.get("database"), dict):
        raw["database"]["url"] = database_url

    qdrant_url = os.getenv("QDRANT_URL")
    store = raw.get("store")
    if qdrant_url and isinstance(store, dict) and store.get("type") in ("qdrant", "store/qdrant"):
        store["url"] = qdrant_url

    milvus_uri = os.getenv("MILVUS_URI")
    if milvus_uri and isinstance(store, dict) and store.get("type") in ("milvus", "store/milvus"):
        store["uri"] = milvus_uri

    opensearch_url = os.getenv("OPENSEARCH_URL")
    sparse = raw.get("sparse")
    if opensearch_url and isinstance(sparse, dict) and (sparse.get("type") or sparse.get("name")) in ("opensearch_bm25", "sparse/opensearch_bm25"):
        sparse["url"] = opensearch_url


def _resolve_model_paths(raw: dict) -> None:
    _resolve_component(raw, "dense", {
        "test_dense": "dense",
        "bge-base-zh-v1.5": "AI-ModelScope/bge-base-zh-v1.5",
        "bge_base": "AI-ModelScope/bge-base-zh-v1.5",
        "bge_base_zh_v15": "AI-ModelScope/bge-base-zh-v1.5",
        "bge-m3": "BAAI/bge-m3",
        "bge_m3": "BAAI/bge-m3",
    })
    _resolve_sparse_components(raw, {
        "bge-m3": "BAAI/bge-m3",
        "bge_m3": "BAAI/bge-m3",
    })
    _resolve_component(raw, "rerank", {
        "test_rerank": "rerank",
        "bge-reranker-base": "BAAI/bge-reranker-base",
        "bge-reranker-large": "BAAI/bge-reranker-large",
        "bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3",
        "bge_base": "BAAI/bge-reranker-base",
        "bge_large": "BAAI/bge-reranker-large",
        "bge_m3": "BAAI/bge-reranker-v2-m3",
        "bge_reranker_base": "BAAI/bge-reranker-base",
        "bge_reranker_large": "BAAI/bge-reranker-large",
        "bge_reranker_v2_m3": "BAAI/bge-reranker-v2-m3",
    })
    _resolve_component(raw, "ocr", {
        "test_ocr": "ocr",
        "rapid": "RapidAI/RapidOCR",
        "paddle": "PaddlePaddle/PaddleOCR",
        "rapidocr": "RapidAI/RapidOCR",
        "paddleocr": "PaddlePaddle/PaddleOCR",
        "tesseract": "tesseract",
    })


def _select_enabled_components(raw: dict) -> None:
    for section_name in ("dense", "sparse", "store", "rerank", "ocr"):
        section = raw.get(section_name)
        if not _is_component_group(section):
            continue
        if section_name == "sparse" and ("app" in section or "vector" in section):
            raise ValueError("sparse must define exactly one backend")
        enabled = [
            (name, dict(config))
            for name, config in section.items()
            if isinstance(config, dict) and bool(config.get("enable"))
        ]
        if section_name in ("sparse", "rerank") and not enabled:
            raw[section_name] = None
            continue
        if len(enabled) != 1:
            raise ValueError(f"{section_name} must enable exactly one component")
        selected_name, selected = enabled[0]
        selected.pop("enable", None)
        selected.setdefault("name", selected.get("module") or selected_name)
        if section_name == "sparse":
            selected.setdefault("type", selected.get("module") or selected_name)
        if section_name == "store":
            selected.setdefault("type", selected.get("module") or selected_name)
        raw[section_name] = selected


def _available_components(raw: dict) -> dict[str, list[dict[str, object]]]:
    return {
        "store": _component_options(raw.get("store")),
        "sparse": _component_options(raw.get("sparse")),
        "rerank": _component_options(raw.get("rerank")),
        "ocr": _component_options(raw.get("ocr")),
    }


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


def _resolve_sparse_components(raw: dict, model_by_name: dict[str, str]) -> None:
    section = raw.get("sparse")
    if not isinstance(section, dict):
        return
    _resolve_component(raw, "sparse", model_by_name)


def _resolve_component(raw: dict, section_name: str, model_by_name: dict[str, str]) -> None:
    name = raw.get(section_name)
    if section_name == "sparse" and isinstance(name, dict):
        sparse_type = name.get("type") or name.get("name")
        model_name = name.get("model_name") or sparse_type
        if model_name:
            name["model_path"] = _model_path(model_name, model_by_name)
        return
    if isinstance(name, dict):
        model_name = name.get("model_name") or name.get("name")
        if model_name:
            name["model_path"] = _model_path(model_name, model_by_name)
        return
    if not isinstance(name, str):
        return
    section = {"name": name}
    if name in model_by_name:
        section["model_path"] = _model_path(name, model_by_name)
    raw[section_name] = section


def _model_path(model_name: str, model_by_name: dict[str, str]) -> str:
    return str(MODELS_DIR / model_by_name.get(model_name, model_name))
