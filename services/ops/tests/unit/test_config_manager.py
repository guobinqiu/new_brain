from pathlib import Path

import pytest

from services.ops.app.config_manager import ConfigManager


def test_config_manager_reads_and_writes_allowed_config(tmp_path):
    root = tmp_path
    path = root / "services/inference/config"
    path.mkdir(parents=True)
    (path / "inference.yaml").write_text("embedded:\n  enable: true\n", encoding="utf-8")

    manager = ConfigManager(root)

    item = manager.read("inference")
    assert item.name == "inference"
    assert item.path == "services/inference/config/inference.yaml"
    assert item.service == "brain_inference"
    assert "embedded" in item.content

    manager.validate("inference", "tei:\n  enable: true\n")
    manager.write("inference", "tei:\n  enable: true\n")

    assert (path / "inference.yaml").read_text(encoding="utf-8") == "tei:\n  enable: true\n"


def test_config_manager_manages_deploy_env_without_yaml_validation(tmp_path):
    root = tmp_path
    deploy_path = root / "deploy"
    deploy_path.mkdir()
    (deploy_path / ".env").write_text("DATABASE_URL=postgresql://rag:rag@host/rag\n", encoding="utf-8")
    manager = ConfigManager(root)

    item = manager.read("deploy_env")
    assert item.name == "deploy_env"
    assert item.path == "deploy/.env"
    assert item.service is None
    assert item.requires_deploy is True

    manager.validate("deploy_env", "DATABASE_URL=postgresql://rag:rag@host/rag\nVALUE=[\n")
    manager.write("deploy_env", "A=1\n# comment\nEMPTY=\n")

    assert (deploy_path / ".env").read_text(encoding="utf-8") == "A=1\n# comment\nEMPTY=\n"


def test_config_manager_manages_stack_yaml_as_deploy_config(tmp_path):
    root = tmp_path
    deploy_path = root / "deploy"
    deploy_path.mkdir()
    (deploy_path / "deploy.yaml").write_text("services:\n  rag:\n    image: brain-rag:dev\n", encoding="utf-8")
    manager = ConfigManager(root)

    item = manager.read("stack")
    assert item.name == "stack"
    assert item.path == "deploy/deploy.yaml"
    assert item.service is None
    assert item.requires_deploy is True
    manager.validate("stack", "services:\n  rag:\n    image: brain-rag:dev\n")


def test_config_manager_rejects_unknown_or_invalid_config(tmp_path):
    manager = ConfigManager(tmp_path)

    with pytest.raises(KeyError):
        manager.read("unknown")

    with pytest.raises(ValueError):
        manager.validate("inference", "embedded: [")

    with pytest.raises(ValueError):
        manager.validate("deploy_env", "bad env line")
