from __future__ import annotations

import os
from pathlib import Path

import yaml

from schema import AppConfig, parse_app_config


CONFIG_DIR = Path(__file__).resolve().parent / "config"
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_CONFIG_FILE = "local.yaml"
CONFIG_FILE_ENV = "CONFIG_FILE"


def load_app_config() -> AppConfig:
    config_path = os.getenv(CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE)
    return load_config_file(_resolve_config_path(config_path))


def load_config_file(path: str | Path) -> AppConfig:
    config_path = _resolve_config_path(str(path))
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    _select_enabled_components(raw)
    _resolve_model_paths(raw)
    config = parse_app_config(raw)
    object.__setattr__(config, "name", config_path.stem)
    return config


def _resolve_config_path(value: str) -> Path:
    config_path = Path(value)
    if config_path.is_absolute() or config_path.exists():
        return config_path
    if config_path.parts and config_path.parts[0] == "config":
        return BACKEND_DIR / config_path
    return CONFIG_DIR / config_path


def _resolve_model_paths(raw: dict) -> None:
    _resolve_component(raw, "dense", {
        "test_dense": "dense",
        "bge_base": "bge-base-zh-v1.5",
        "bge_base_zh_v15": "bge-base-zh-v1.5",
        "bge_m3": "bge-m3",
    })
    _resolve_component(raw, "sparse", {
        "bge_m3": "bge-m3",
    })
    _resolve_component(raw, "rerank", {
        "test_rerank": "rerank",
        "bge_base": "bge-reranker-base",
        "bge_large": "bge-reranker-large",
        "bge_m3": "bge-reranker-v2-m3",
        "bge_reranker_base": "bge-reranker-base",
        "bge_reranker_large": "bge-reranker-large",
        "bge_reranker_v2_m3": "bge-reranker-v2-m3",
    })
    _resolve_component(raw, "ocr", {
        "test_ocr": "ocr",
        "rapid": "rapidocr",
        "paddle": "paddleocr",
        "rapidocr": "rapidocr",
        "paddleocr": "paddleocr",
        "tesseract": "tesseract",
    })


def _select_enabled_components(raw: dict) -> None:
    for section_name in ("dense", "sparse", "store", "rerank", "ocr"):
        section = raw.get(section_name)
        if not _is_component_group(section):
            continue
        enabled = [
            (name, dict(config))
            for name, config in section.items()
            if isinstance(config, dict) and bool(config.get("enable"))
        ]
        if section_name == "rerank" and not enabled:
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


def _is_component_group(section) -> bool:
    if not isinstance(section, dict):
        return False
    if any(key in section for key in ("name", "type", "module", "collections")):
        return False
    return all(isinstance(value, dict) for value in section.values())


def _resolve_component(raw: dict, section_name: str, model_by_name: dict[str, str]) -> None:
    name = raw.get(section_name)
    if section_name == "sparse" and isinstance(name, dict):
        sparse_type = name.get("type") or name.get("name")
        model_name = name.get("model_name") or model_by_name.get(sparse_type)
        if model_name:
            name["model_path"] = str(MODELS_DIR / model_name)
        return
    if isinstance(name, dict):
        model_name = name.get("model_name") or model_by_name.get(name.get("name"))
        if model_name:
            name["model_path"] = str(MODELS_DIR / model_name)
        return
    if not isinstance(name, str):
        return
    section = {"name": name}
    if name in model_by_name:
        section["model_path"] = str(MODELS_DIR / model_by_name[name])
    raw[section_name] = section
