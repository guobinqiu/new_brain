from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared.config import DenseConfig, RerankConfig, RetryConfig, SparseConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "services/inference/config/inference.yaml"


@dataclass(frozen=True)
class SiliconFlowConfig:
    base_url: str
    api_key: str | None = field(repr=False)
    dense_model: str
    rerank_model: str | None
    dimensions: int | None = None
    dense_timeout: int = 60
    rerank_timeout: int | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class VolcengineConfig:
    base_url: str
    api_key: str = field(repr=False)
    dense_model: str
    dimensions: int = 2048
    sparse_model: str | None = None
    rerank_model: str | None = None
    dense_timeout: int = 60
    sparse_timeout: int | None = None
    rerank_timeout: int | None = None
    rerank_base_url: str | None = None
    region: str | None = None
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class TeiConfig:
    dense_url: str
    dense_model: str
    rerank_url: str | None = None
    rerank_model: str | None = None
    dimensions: int | None = None
    dense_timeout: float = 60.0
    rerank_timeout: float | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class VllmConfig:
    dense_url: str
    dense_model: str
    rerank_url: str | None = None
    rerank_model: str | None = None
    dimensions: int | None = None
    dense_timeout: float = 60.0
    rerank_timeout: float | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class InferenceConfig:
    dense: DenseConfig | None
    sparse: SparseConfig | None
    rerank: RerankConfig | None
    siliconflow: SiliconFlowConfig | None = None
    volcengine: VolcengineConfig | None = None
    tei: TeiConfig | None = None
    vllm: VllmConfig | None = None


def load_inference_config(config_file: str | Path | None = None) -> InferenceConfig:
    with _resolve_config_path(config_file).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    selected = _select_enabled(raw, "inference", required=True)
    if _provider_name(selected) == "siliconflow":
        dense = _select_enabled(selected.get("dense"), "dense", required=True)
        rerank = _select_enabled(selected.get("rerank"), "rerank", required=False)
        return InferenceConfig(dense=None, sparse=None, rerank=None, siliconflow=SiliconFlowConfig(
            base_url=_required(selected, "base_url", "siliconflow"),
            api_key=os.environ[_siliconflow_api_key_env(selected["name"])],
            dense_model=dense["model_name"],
            rerank_model=rerank["model_name"] if rerank else None,
            dimensions=dense.get("dimensions"),
            dense_timeout=int(dense.get("timeout", 60)),
            rerank_timeout=int(rerank.get("timeout", 60)) if rerank else None,
            retry=_parse_retry_config(selected.get("retry")),
        ))
    if _provider_name(selected) == "volcengine":
        dense = _select_enabled(selected.get("dense"), "dense", required=True)
        sparse = _select_enabled(selected.get("sparse"), "sparse", required=False)
        rerank = _select_enabled(selected.get("rerank"), "rerank", required=False)
        rerank_model = rerank["model_name"] if rerank else None
        return InferenceConfig(dense=None, sparse=None, rerank=None, volcengine=VolcengineConfig(
            base_url=_required(selected, "base_url", "volcengine"),
            api_key=os.environ["ARK_API_KEY"],
            dense_model=dense["model_name"],
            dimensions=dense.get("dimensions", 2048),
            sparse_model=sparse["model_name"] if sparse else None,
            rerank_model=rerank_model,
            dense_timeout=int(dense.get("timeout", 60)),
            sparse_timeout=int(sparse.get("timeout", 60)) if sparse else None,
            rerank_timeout=int(rerank.get("timeout", 60)) if rerank else None,
            rerank_base_url=_required(selected, "rerank_base_url", "volcengine") if rerank_model else None,
            region=_required(selected, "region", "volcengine") if rerank_model else None,
            access_key=os.environ["VIKING_ACCESS_KEY"] if rerank_model else None,
            secret_key=os.environ["VIKING_SECRET_KEY"] if rerank_model else None,
            retry=_parse_retry_config(selected.get("retry")),
        ))
    if _provider_name(selected) == "tei":
        dense = _select_enabled(selected.get("dense"), "dense", required=True)
        rerank = _select_enabled(selected.get("rerank"), "rerank", required=False)
        return InferenceConfig(dense=None, sparse=None, rerank=None, tei=TeiConfig(
            dense_url=_required(dense, "base_url", "dense"),
            dense_model=dense["model_name"],
            rerank_url=_required(rerank, "base_url", "rerank") if rerank else None,
            rerank_model=rerank["model_name"] if rerank else None,
            dimensions=dense.get("dimensions"),
            dense_timeout=float(dense.get("timeout", 60)),
            rerank_timeout=float(rerank.get("timeout", 60)) if rerank else None,
            retry=_parse_retry_config(selected.get("retry")),
        ))
    if _provider_name(selected) == "vllm":
        dense = _select_enabled(selected.get("dense"), "dense", required=True)
        rerank = _select_enabled(selected.get("rerank"), "rerank", required=False)
        return InferenceConfig(dense=None, sparse=None, rerank=None, vllm=VllmConfig(
            dense_url=_required(dense, "base_url", "dense"),
            dense_model=dense["model_name"],
            rerank_url=_required(rerank, "base_url", "rerank") if rerank else None,
            rerank_model=rerank["model_name"] if rerank else None,
            dimensions=dense.get("dimensions"),
            dense_timeout=float(dense.get("timeout", 60)),
            rerank_timeout=float(rerank.get("timeout", 60)) if rerank else None,
            retry=_parse_retry_config(selected.get("retry")),
        ))
    if _provider_name(selected) != "embedded":
        raise ValueError(f"unsupported inference provider: {selected['name']}")
    return InferenceConfig(
        dense=_parse_dense(selected.get("dense") or {}),
        sparse=_parse_sparse(selected.get("sparse")),
        rerank=_parse_rerank(selected.get("rerank")),
    )


def _parse_dense(raw: dict[str, Any]) -> DenseConfig:
    selected = _select_enabled(raw, "dense", required=True)
    name = _required(selected, "name", "dense")
    model_name = selected.get("model_name") or name
    return DenseConfig(
        name=name,
        model_name=model_name,
        model_path=_model_path(model_name),
        batch_size=int(selected.get("batch_size", 4)),
        release_memory=selected.get("release_memory", "per_batch"),
    )


def _parse_sparse(raw: Any) -> SparseConfig | None:
    selected = _select_enabled(raw, "sparse", required=False)
    if selected is None:
        return None
    name = _required(selected, "name", "sparse")
    model_name = selected.get("model_name") or name
    return SparseConfig(
        name=name,
        model_name=model_name,
        model_path=_model_path(model_name),
        batch_size=int(selected.get("batch_size", 4)),
        release_memory=selected.get("release_memory", "per_batch"),
    )


def _parse_rerank(raw: Any) -> RerankConfig | None:
    selected = _select_enabled(raw, "rerank", required=False)
    if selected is None:
        return None
    name = selected.get("name")
    if name is None:
        raise ValueError("rerank.name is required")
    model_name = selected.get("model_name") or name
    return RerankConfig(
        name=name,
        model_name=model_name,
        model_path=_model_path(model_name),
    )


def _parse_retry_config(raw: Any) -> RetryConfig:
    if raw is None:
        return RetryConfig()
    if not isinstance(raw, dict):
        raise ValueError("retry config must be an object")
    return RetryConfig(
        max_attempts=max(1, int(raw.get("max_attempts", 3))),
        interval_seconds=max(0.0, float(raw.get("interval_seconds", 0.5))),
    )


def _provider_name(selected: dict[str, Any]) -> str:
    name = str(selected.get("name", ""))
    if name.startswith("siliconflow-"):
        return "siliconflow"
    return name


def _siliconflow_api_key_env(name: str) -> str:
    if name == "siliconflow-cn":
        return "SILICONFLOW_CN_API_KEY"
    if name == "siliconflow-intl":
        return "SILICONFLOW_INTL_API_KEY"
    raise ValueError(f"unsupported siliconflow provider: {name}")


def _select_enabled(raw: Any, section_name: str, *, required: bool) -> dict[str, Any] | None:
    if raw is None:
        if required:
            raise ValueError(f"{section_name} must enable exactly one component")
        return None
    if not isinstance(raw, dict):
        raise ValueError("component config must be an object")
    if "name" in raw or "type" in raw:
        return raw
    enabled = [
        (name, dict(config))
        for name, config in raw.items()
        if isinstance(config, dict) and _bool(config.get("enable", False))
    ]
    if not enabled:
        if required:
            raise ValueError(f"{section_name} must enable exactly one component")
        return None
    if len(enabled) != 1:
        if required:
            raise ValueError(f"{section_name} must enable exactly one component")
        raise ValueError(f"{section_name} must enable at most one component")
    name, config = enabled[0]
    config.pop("enable", None)
    config.setdefault("name", name)
    config.setdefault("type", name)
    return config


def _model_path(model_name: str) -> str:
    return str(MODELS_DIR / model_name)


def _resolve_config_path(value: str | Path | None) -> Path:
    if value is None:
        return DEFAULT_CONFIG_FILE
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    if path.parts and path.parts[0] in ("rag", "services"):
        return PROJECT_ROOT / path
    return Path.cwd() / path


def _required(section: dict[str, Any], key: str, section_name: str) -> Any:
    value = section.get(key)
    if value is None:
        raise ValueError(f"{section_name}.{key} is required")
    return value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)
