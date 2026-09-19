from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.config import MineruCloudParserConfig, MineruParserConfig, ParserConfig, RetryConfig, VolcengineParserConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "services/parser/config/parser.yaml"


def load_parser_config(config_file: str | Path | None = None) -> ParserConfig:
    with _resolve_config_path(config_file).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    parser = raw.get("parser") or {}
    active = _select_enabled_backend(parser, ("mineru", "mineru_cloud", "volcengine"))
    volcengine = parser.get("volcengine") or {}
    cloud = parser.get("mineru_cloud") or {}
    return ParserConfig(
        active=active,
        download_timeout=int(parser.get("download_timeout", 60)),
        mineru=_parse_mineru_config(parser.get("mineru") or {}),
        mineru_cloud=MineruCloudParserConfig(
            enable=active == "mineru_cloud",
            base_url=cloud.get("base_url", "https://mineru.net"),
            timeout=int(cloud.get("timeout", 300)),
            model_version=cloud.get("model_version", "vlm"),
            enable_formula=bool(cloud.get("enable_formula", True)),
            enable_table=bool(cloud.get("enable_table", True)),
            language=cloud.get("language", "ch"),
            retry=_parse_retry_config(cloud.get("retry")),
            api_key=_env_value("MINERU_API_KEY"),
        ),
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
    tier = str(raw.get("tier", "basic"))
    parse_method = str(raw.get("parse_method", "auto"))
    if tier not in {"flash", "basic", "standard", "advanced"}:
        raise ValueError(f"unsupported mineru.tier: {tier}")
    if parse_method not in {"auto", "ocr", "txt"}:
        raise ValueError(f"unsupported mineru.parse_method: {parse_method}")
    return MineruParserConfig(
        enable=bool(raw.get("enable", False)),
        tier=tier,
        parse_method=parse_method,
        image_analysis=bool(raw.get("image_analysis", False)),
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
