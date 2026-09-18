from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.config import DoclingParserConfig, DoclingVlmParserConfig, MineruParserConfig, ParserConfig, RetryConfig, VolcengineParserConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "services/parser/config/parser.yaml"


def load_parser_config(config_file: str | Path | None = None) -> ParserConfig:
    with _resolve_config_path(config_file).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    parser = raw.get("parser") or {}
    active = _select_enabled_backend(parser, ("mineru", "docling", "docling_vlm", "volcengine"))
    volcengine = parser.get("volcengine") or {}
    return ParserConfig(
        active=active,
        mineru=_parse_mineru_config(parser.get("mineru") or {}),
        docling=_parse_docling_config(parser.get("docling") or {}),
        docling_vlm=_parse_docling_vlm_config(parser.get("docling_vlm") or {}),
        volcengine=VolcengineParserConfig(
            enable=active == "volcengine",
            model=volcengine["model"] if active == "volcengine" else volcengine.get("model"),
            prompt=volcengine["prompt"] if active == "volcengine" else volcengine.get("prompt"),
            thinking=bool(volcengine.get("thinking", False)),
            stream=bool(volcengine.get("stream", False)),
            service_tier=volcengine.get("service_tier", "auto"),
            timeout=int(volcengine.get("timeout", 300)),
            base_url=volcengine["base_url"] if active == "volcengine" else volcengine.get("base_url"),
            retry=_parse_retry_config(volcengine.get("retry")),
            api_key=_env_value("ARK_API_KEY") if active == "volcengine" else None,
        ),
    )


def _parse_mineru_config(raw: dict[str, Any]) -> MineruParserConfig:
    return MineruParserConfig(
        enable=bool(raw.get("enable", False)),
        parse_method=str(raw.get("parse_method", "auto")),
        formula=bool(raw.get("formula", True)),
        table_enable=bool(raw.get("table", True)),
        base_url=raw.get("base_url"),
        timeout=int(raw.get("timeout", 300)),
        tier=str(raw.get("tier", "standard")),
        retry=_parse_retry_config(raw.get("retry")),
        api_key=_env_value("MINERU_API_KEY"),
    )


def _parse_docling_config(raw: dict[str, Any]) -> DoclingParserConfig:
    table_mode = str(raw.get("table_mode", "accurate"))
    if table_mode not in {"fast", "accurate"}:
        raise ValueError(f"unsupported docling.table_mode: {table_mode}, supported values: fast, accurate")
    return DoclingParserConfig(
        enable=bool(raw.get("enable", False)),
        formula=bool(raw.get("formula", True)),
        table_enable=bool(raw.get("table", True)),
        table_mode=table_mode,
    )


def _parse_docling_vlm_config(raw: dict[str, Any]) -> DoclingVlmParserConfig:
    return DoclingVlmParserConfig(
        enable=bool(raw.get("enable", False)),
        model=raw.get("model") or "granitedocling",
    )


def _select_enabled_backend(parser: dict[str, Any], names: tuple[str, ...]) -> str:
    backends = {
        name: parser.get(name)
        for name in names
        if isinstance(parser.get(name), dict)
    }
    enabled = [name for name, config in backends.items() if bool(config.get("enable"))]
    if len(enabled) != 1:
        raise ValueError("parser must enable exactly one backend")
    return enabled[0]


def _parse_retry_config(raw: Any) -> RetryConfig:
    if raw is None:
        return RetryConfig()
    return RetryConfig(
        max_attempts=max(1, int(raw.get("max_attempts", 3))),
        interval_seconds=max(0.0, float(raw.get("interval_seconds", 0.5))),
    )


def _resolve_config_path(value: str | Path | None) -> Path:
    if value is None:
        return DEFAULT_CONFIG_FILE
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    if path.parts and path.parts[0] in ("rag", "services"):
        return PROJECT_ROOT / path
    return Path.cwd() / path


def _env_value(name: str) -> str | None:
    import os

    value = os.environ.get(name)
    return value if value else None
