from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ConfigFile:
    name: str
    path: str
    service: str | None
    content: str
    requires_deploy: bool


@dataclass(frozen=True)
class ConfigSpec:
    name: str
    path: str
    service: str | None
    format: str = "yaml"
    requires_deploy: bool = False


CONFIG_SPECS = {
    "rag": ConfigSpec(name="rag", path="services/rag/config/rag.yaml", service="brain_rag"),
    "parser": ConfigSpec(name="parser", path="services/parser/config/parser.yaml", service="brain_parser"),
    "inference": ConfigSpec(name="inference", path="services/inference/config/inference.yaml", service="brain_inference"),
    "llm": ConfigSpec(name="llm", path="services/llm/config/llm.yaml", service="brain_llm"),
    "deploy_env": ConfigSpec(name="deploy_env", path="deploy/.env", service=None, format="env", requires_deploy=True),
    "stack": ConfigSpec(name="stack", path="deploy/deploy.yaml", service=None, requires_deploy=True),
    "infra": ConfigSpec(name="infra", path="deploy/infra.yaml", service=None, requires_deploy=True),
}


class ConfigManager:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def list(self) -> list[dict]:
        return [
            {
                "name": spec.name,
                "path": spec.path,
                "service": spec.service,
                "requires_deploy": spec.requires_deploy,
            }
            for spec in CONFIG_SPECS.values()
        ]

    def read(self, name: str) -> ConfigFile:
        spec = self._spec(name)
        return ConfigFile(
            name=spec.name,
            path=spec.path,
            service=spec.service,
            content=self._path(spec).read_text(encoding="utf-8"),
            requires_deploy=spec.requires_deploy,
        )

    def validate(self, name: str, content: str) -> None:
        spec = self._spec(name)
        if spec.format == "env":
            self._validate_env(content)
            return
        self._validate_yaml(content)

    def write(self, name: str, content: str) -> ConfigFile:
        self.validate(name, content)
        spec = self._spec(name)
        path = self._path(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(path, content)
        return self.read(name)

    def _spec(self, name: str) -> ConfigSpec:
        if name not in CONFIG_SPECS:
            raise KeyError(name)
        return CONFIG_SPECS[name]

    def _path(self, spec: ConfigSpec) -> Path:
        path = (self.root / spec.path).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError("config path escapes project root")
        return path

    def _validate_yaml(self, content: str) -> None:
        try:
            yaml.safe_load(content) if content.strip() else None
        except yaml.YAMLError as exc:
            raise ValueError(str(exc)) from exc

    def _validate_env(self, content: str) -> None:
        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                raise ValueError(f"invalid env line {line_no}: missing '='")
            key = stripped.split("=", 1)[0].strip()
            if not key or any(char.isspace() for char in key):
                raise ValueError(f"invalid env line {line_no}: invalid key")

    def _write_atomic(self, path: Path, content: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
