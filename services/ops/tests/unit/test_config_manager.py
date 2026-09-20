from pathlib import Path
import os
import stat
from unittest.mock import patch

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


def test_config_manager_manages_env_without_yaml_validation(tmp_path):
    root = tmp_path
    deploy_path = root / "deploy"
    deploy_path.mkdir()
    (deploy_path / ".env").write_text("DATABASE_URL=postgresql://rag:rag@host/rag\n", encoding="utf-8")
    manager = ConfigManager(root)

    item = manager.read("env")
    assert item.name == "env"
    assert item.path == "deploy/.env"
    assert item.service is None
    assert item.requires_deploy is True

    manager.validate("env", "DATABASE_URL=postgresql://rag:rag@host/rag\nVALUE=[\n")
    manager.write("env", "A=1\n# comment\nEMPTY=\n")

    assert (deploy_path / ".env").read_text(encoding="utf-8") == "A=1\n# comment\nEMPTY=\n"


def test_config_manager_manages_deploy_yaml_as_deploy_config(tmp_path):
    root = tmp_path
    deploy_path = root / "deploy"
    deploy_path.mkdir()
    (deploy_path / "deploy.yaml").write_text("services:\n  rag:\n    image: brain-rag:dev\n", encoding="utf-8")
    manager = ConfigManager(root)

    item = manager.read("deploy")
    assert item.name == "deploy"
    assert item.path == "deploy/deploy.yaml"
    assert item.service is None
    assert item.requires_deploy is True
    manager.validate("deploy", "services:\n  rag:\n    image: brain-rag:dev\n")


def test_config_manager_rejects_unknown_or_invalid_config(tmp_path):
    manager = ConfigManager(tmp_path)

    with pytest.raises(KeyError):
        manager.read("unknown")

    with pytest.raises(ValueError):
        manager.validate("inference", "embedded: [")

    with pytest.raises(ValueError):
        manager.validate("env", "bad env line")


def test_config_manager_manages_infra_separately(tmp_path):
    manager = ConfigManager(tmp_path)
    item = manager.write("infra", "services: {}\n")
    assert item.path == "deploy/infra.yaml"
    assert item.requires_deploy is True
    assert not (tmp_path / "deploy/deploy.yaml").exists()


def test_atomic_write_preserves_permissions_and_owner(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o640)
    before = path.stat()

    ConfigManager(tmp_path)._write_atomic(path, "A=2\n")

    after = path.stat()
    assert stat.S_IMODE(after.st_mode) == 0o640
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert path.read_text() == "A=2\n"


def test_atomic_write_restores_owner_before_replace(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    original = path.stat()
    real_fstat = os.fstat
    calls = []

    def different_owner(fd):
        values = list(real_fstat(fd))
        values[4] = original.st_uid + 1
        return os.stat_result(values)

    with patch("os.fstat", side_effect=different_owner), patch("os.fchown", side_effect=lambda fd, uid, gid: calls.append((uid, gid))):
        ConfigManager(tmp_path)._write_atomic(path, "A=2\n")

    assert calls == [(original.st_uid, original.st_gid)]


def test_atomic_write_failure_keeps_original_and_removes_temp(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n")

    with patch("os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            ConfigManager(tmp_path)._write_atomic(path, "A=2\n")

    assert path.read_text() == "A=1\n"
    assert list(tmp_path.iterdir()) == [path]
