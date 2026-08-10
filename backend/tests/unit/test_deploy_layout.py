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


def test_backend_mounts_database_dirs_without_docker_subdirectories():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert "../../chroma_data:/app/chroma_data" in compose
        assert "../../milvus_data/lite:/app/milvus_data/lite" in compose
        assert "../../chroma_data/docker:/app/chroma_data" not in compose
        assert "../../milvus_data/lite/docker:/app/milvus_data" not in compose


def test_service_database_dirs_are_grouped_by_database():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert "../../qdrant_data:/qdrant/storage" in compose
        assert "../../qdrant_data/docker:/qdrant/storage" not in compose
        assert "../../milvus_data/standalone/etcd:/etcd" in compose
        assert "../../milvus_data/standalone/minio:/minio_data" in compose
        assert "../../milvus_data/standalone/milvus:/var/lib/milvus" in compose


def test_backend_passes_optional_langsmith_environment_to_container():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert "LANGSMITH_TRACING: ${LANGSMITH_TRACING:-false}" in compose
        assert "LANGSMITH_API_KEY: ${LANGSMITH_API_KEY:-}" in compose
        assert "LANGSMITH_PROJECT: ${LANGSMITH_PROJECT:-rag-search}" in compose
        assert "LANGSMITH_ENDPOINT: ${LANGSMITH_ENDPOINT:-https://api.smith.langchain.com}" in compose


def test_deploy_uses_matching_backend_config_file():
    cpu_compose = (ROOT / "deploy/cpu/docker-compose.yml").read_text(encoding="utf-8")
    gpu_compose = (ROOT / "deploy/gpu/docker-compose.yml").read_text(encoding="utf-8")

    assert "CONFIG_FILE: ${CONFIG_FILE:-docker-cpu.yaml}" in cpu_compose
    assert "CONFIG_FILE: ${CONFIG_FILE:-docker-gpu.yaml}" in gpu_compose
    assert "CONFIG_FILE: ${CONFIG_FILE:-docker.yaml}" not in cpu_compose
    assert "CONFIG_FILE: ${CONFIG_FILE:-docker.yaml}" not in gpu_compose


def test_deploy_services_use_bounded_json_file_logs():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert 'driver: "json-file"' in compose
        assert 'max-size: "10m"' in compose
        assert 'max-file: "5"' in compose
