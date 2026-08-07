from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]


def test_deploy_has_separate_cpu_and_gpu_entries():
    assert (ROOT / "deploy/cpu/Dockerfile").exists()
    assert (ROOT / "deploy/cpu/docker-compose.yml").exists()
    assert (ROOT / "deploy/gpu/Dockerfile").exists()
    assert (ROOT / "deploy/gpu/docker-compose.yml").exists()


def test_cpu_deploy_installs_cpu_extra():
    dockerfile = (ROOT / "deploy/cpu/Dockerfile").read_text(encoding="utf-8")

    command = dockerfile.split("CMD", 1)[1]

    assert "RUN uv sync --extra cpu" in dockerfile
    assert "uv sync" not in command
    assert '"uv", "run"' not in dockerfile
    assert 'CMD ["/app/.venv/bin/uvicorn"' in dockerfile
    assert "--extra ocr" not in dockerfile
    assert "uv sync --extra gpu" not in dockerfile


def test_gpu_deploy_installs_gpu_extra_and_exposes_gpu():
    dockerfile = (ROOT / "deploy/gpu/Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/gpu/docker-compose.yml").read_text(encoding="utf-8")

    command = dockerfile.split("CMD", 1)[1]

    assert "RUN uv sync --extra gpu" in dockerfile
    assert "uv sync" not in command
    assert '"uv", "run"' not in dockerfile
    assert 'CMD ["/app/.venv/bin/uvicorn"' in dockerfile
    assert "--extra ocr" not in dockerfile
    assert "driver: nvidia" in compose
    assert "count: all" in compose
    assert "capabilities: [gpu]" in compose
    assert "NVIDIA_VISIBLE_DEVICES" not in compose
    assert "NVIDIA_DRIVER_CAPABILITIES" not in compose


def test_backend_venv_is_not_mounted_over_image_environment():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert ".venv-docker" not in compose
        assert "../../backend/.venv-docker:/app/backend/.venv-docker" not in compose


def test_embedded_database_dirs_are_separate_for_docker():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert "../../chroma_data/docker:/app/chroma_data" in compose
        assert "../../milvus_data/lite/docker:/app/milvus_data" in compose
        assert "../../chroma_data:/app/chroma_data" not in compose
        assert "../../milvus_data:/app/milvus_data" not in compose


def test_service_database_dirs_are_grouped_by_database():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert "../../qdrant_data/docker:/qdrant/storage" in compose
        assert "../../milvus_data/standalone/etcd:/etcd" in compose
        assert "../../milvus_data/standalone/minio:/minio_data" in compose
        assert "../../milvus_data/standalone/milvus:/var/lib/milvus" in compose
